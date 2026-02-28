import asyncio
import logging
import os
from asyncio import CancelledError
from datetime import datetime

import websockets
from dotenv import load_dotenv
from google.genai.errors import APIError
from vision_agents.core import Agent, AgentLauncher, Runner, User
from vision_agents.plugins import gemini, getstream, ultralytics
from vision_agents.plugins.gemini.gemini_realtime import (
    GeminiRealtime,
    _should_reconnect,
)

from roboflow_processor import RoboflowProcessor

load_dotenv()

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Monkey-patch: fix APIError reconnection in the Gemini processing loop.
#
# The framework's _processing_loop only catches websockets.ConnectionClosedError
# for reconnection, but the google-genai SDK wraps that as an APIError.  When a
# 1011 (session timeout / internal error) arrives, the APIError falls into the
# generic ``except Exception`` handler which just logs and continues -- leaving
# the WebSocket dead and the loop spinning forever.
#
# This patch adds an ``except APIError`` clause that checks _should_reconnect
# and reconnects when appropriate, matching the existing ConnectionClosedError
# behaviour.
# ---------------------------------------------------------------------------

async def _patched_processing_loop(self: GeminiRealtime):  # type: ignore[arg-type]
    _logger.debug("Start processing events from Gemini Live API (patched)")
    try:
        while True:
            try:
                await self._process_events()
            except websockets.ConnectionClosedError as e:
                if not _should_reconnect(e):
                    raise
                _logger.warning("Reconnecting after ConnectionClosedError (%s)", e)
                await self.connect()
            except APIError as e:
                if _should_reconnect(e):
                    _logger.warning("Reconnecting after APIError (%s)", e)
                    await self.connect()
                else:
                    _logger.exception("Non-recoverable APIError from Gemini Live API")
            except Exception:
                _logger.exception("Error while processing events from Gemini Live API")
    except CancelledError:
        _logger.debug("Processing loop has been cancelled")

GeminiRealtime._processing_loop = _patched_processing_loop  # type: ignore[assignment]

PROTOCOL_INSTRUCTIONS = """\
You are a medical proctor AI supervising a medication administration procedure via live video.

Your job is to monitor the procedure in real time, ensure safety protocols are followed,
and provide spoken guidance to the clinician.

## Protocol Steps (in order)

1. **PPE Check** -- Verify the clinician is wearing a mask and gloves before touching anything.
2. **Hand Hygiene** -- Confirm hand washing or sanitiser use.
3. **Medication Identification** -- Verify the medication label is visible and read aloud.
4. **Administration** -- Observe proper technique (correct hand positioning, no contamination).
5. **Documentation** -- Confirm the clinician acknowledges the completed procedure.

## Your Behaviour

- Speak naturally and supportively.  Give short, clear feedback after each observation.
- Tell the user what you are detecting and what objects you see in the video.
- Use **draw_box** to annotate important items you see (PPE, medications, hands, equipment).
- Call **log_step** every time you confirm a protocol step has been completed.
- Call **log_violation** IMMEDIATELY when you detect a safety issue:
    - Missing or improperly worn PPE (no mask, no gloves).
    - Medication handled without gloves.
    - Wrong technique or contamination risk.
    - Any other unsafe act.
- When nothing noteworthy is happening, stay quiet -- do NOT narrate every frame.
- If the Roboflow detector reports objects (masks, gloves, vests, NO-Mask, NO-Safety Vest etc.),
  incorporate that information into your assessment and tell the user what you detect.
"""


async def create_agent(**kwargs) -> Agent:
    agent_llm = gemini.Realtime(
        model="gemini-2.5-flash-native-audio-latest",
        fps=1,
    )

    session_state = {
        "start_time": datetime.now(),
        "protocol_steps": [
            {"step": "PPE Check", "completed": False, "timestamp": None},
            {"step": "Hand Hygiene", "completed": False, "timestamp": None},
            {"step": "Medication Identification", "completed": False, "timestamp": None},
            {"step": "Administration", "completed": False, "timestamp": None},
            {"step": "Documentation", "completed": False, "timestamp": None},
        ],
        "violations": [],
        "detected_ppe": set(),
        "total_detections": 0,
        "recent_reports": [],  # Track recent reports to avoid repetition
        "report_timeout": 10,  # Timeout in seconds before repeating a report
    }

    # ── Tool functions ──────────────────────────────────────────────

    @agent_llm.register_function(
        description="Draw a bounding box on the video. Coordinates are 0-1000."
    )
    async def draw_box(
        label: str,
        ymin: float,
        xmin: float,
        ymax: float,
        xmax: float,
        color: str = "blue",
    ) -> str:
        session_state["total_detections"] += 1
        return f"Annotated {label}"

    @agent_llm.register_function(
        description=(
            "Log that a protocol step has been completed. "
            "step_name must be one of: PPE Check, Hand Hygiene, "
            "Medication Identification, Administration, Documentation."
        )
    )
    async def log_step(step_name: str, details: str) -> str:
        now = datetime.now()
        for entry in session_state["protocol_steps"]:
            if entry["step"].lower() == step_name.strip().lower():
                if not entry["completed"]:
                    entry["completed"] = True
                    entry["timestamp"] = now
                    print(f"  [STEP] {step_name} completed at {now:%H:%M:%S} -- {details}")
                return f"Step '{step_name}' recorded"
        return f"Unknown step '{step_name}'"

    @agent_llm.register_function(
        description=(
            "Log a safety or protocol violation. "
            "violation_type examples: PPE Missing, Technique Error, Safety Risk, Protocol Deviation. "
            "severity must be one of: low, medium, high, critical."
        )
    )
    async def log_violation(
        violation_type: str, description: str, severity: str = "medium"
    ) -> str:
        now = datetime.now()
        severity = severity.lower() if severity.lower() in ("low", "medium", "high", "critical") else "medium"
        entry = {
            "type": violation_type,
            "description": description,
            "severity": severity,
            "timestamp": now,
        }
        session_state["violations"].append(entry)
        print(f"  [VIOLATION][{severity.upper()}] {violation_type}: {description}")
        return f"Violation logged: {violation_type} ({severity})"

    # ── Helper functions ──────────────────────────────────────────────
    
    def is_recent_report(report: str, state: dict) -> bool:
        """Check if a report has been made recently to avoid repetition."""
        current_time = datetime.now().timestamp()
        report_key = report.strip().lower()
        
        for recent_report, timestamp in state["recent_reports"][:]:
            if abs(current_time - timestamp) > state["report_timeout"]:
                # Remove expired report
                state["recent_reports"].remove((recent_report, timestamp))
            elif recent_report == report_key:
                return True  # Report is too recent, don't repeat
        return False
    
    def add_report(report: str, state: dict) -> None:
        """Add a report to the recent reports list."""
        current_time = datetime.now().timestamp()
        report_key = report.strip().lower()
        state["recent_reports"].append((report_key, current_time))

    # ── Processors ──────────────────────────────────────────────────

    roboflow_proc = RoboflowProcessor(
        api_key=os.getenv("ROBOFLOW_API_KEY", ""),
        model_id="personal-protective-equipment-combined-model/14",
        conf_threshold=0.4,
        fps=1,
    )

    yolo_proc = ultralytics.YOLOPoseProcessor(
        model_path="yolo11n.pt",
        conf_threshold=0.5,
    )

    agent = Agent(
        edge=getstream.Edge(),
        agent_user=User(name="Medical Proctor", id="proctor_agent"),
        instructions=PROTOCOL_INSTRUCTIONS,
        llm=agent_llm,
        processors=[yolo_proc, roboflow_proc],
    )

    # ── Events ──────────────────────────────────────────────────────

    @agent.events.subscribe
    async def on_event(event):
        if event.type == "participant_left" and event.participant.user.id != "proctor_agent":
            _print_session_report(session_state)

    # Stash the roboflow processor on the agent so join_call can use it
    agent._roboflow_proc = roboflow_proc  # type: ignore[attr-defined]
    agent._session_state = session_state  # type: ignore[attr-defined]

    return agent


async def join_call(agent: Agent, call_type: str, call_id: str, **kwargs) -> None:
    call = await agent.create_call(call_type, call_id)
    print(f"Connecting to call: {call_id}")

    roboflow_proc: RoboflowProcessor = agent._roboflow_proc  # type: ignore[attr-defined]

    while True:
        try:
            async with agent.join(call):
                await agent.simple_response(
                    "Medical proctor online. I will monitor your medication procedure. "
                    "Please begin by confirming you are wearing proper PPE -- mask and gloves."
                )

                async def evaluate_video_loop():
                    try:
                        await asyncio.sleep(5)
                        for _ in range(60):
                            detections = roboflow_proc.latest_detections
                            summary = detections.get("summary", "") if detections else ""

                            if summary and summary != "nothing detected":
                                # Check if this detection summary has been reported recently
                                if not is_recent_report(summary, session_state):
                                    prompt = (
                                        f"Roboflow detections: {summary}. "
                                        "Assess compliance with the current protocol step. "
                                        "Log steps or violations as appropriate and give brief spoken feedback. "
                                        "Tell the user what you are detecting and make it clear."
                                    )
                                    add_report(summary, session_state)
                                else:
                                    prompt = (
                                        "Observe the current video frame. "
                                        "Only report significant changes or new detections. "
                                        "Focus on protocol steps or violations if present."
                                    )
                            else:
                                prompt = (
                                    "Observe the current video frame. "
                                    "Report any protocol steps completed or violations you see."
                                )

                            await agent.simple_response(prompt)
                            await asyncio.sleep(5)
                    except asyncio.CancelledError:
                        pass

                poller = asyncio.create_task(evaluate_video_loop())
                await agent.finish()
                poller.cancel()
            break
        except Exception as e:
            print(f"\nConnection dropped: {e}")
            await asyncio.sleep(3)


# ── Session report ──────────────────────────────────────────────────


def _print_session_report(state: dict) -> None:
    end_time = datetime.now()
    duration = (end_time - state["start_time"]).total_seconds()

    print()
    print("=" * 60)
    print("  SESSION REPORT")
    print("=" * 60)
    print(f"  Duration : {duration:.0f}s")

    # Protocol completion
    completed = [s for s in state["protocol_steps"] if s["completed"]]
    total = len(state["protocol_steps"])
    print(f"\n  Protocol : {len(completed)}/{total} steps completed")
    for step in state["protocol_steps"]:
        mark = "+" if step["completed"] else "-"
        ts = step["timestamp"].strftime("%H:%M:%S") if step["timestamp"] else "---"
        print(f"    [{mark}] {step['step']:30s}  {ts}")

    # Violations
    violations = state["violations"]
    print(f"\n  Violations: {len(violations)}")
    if violations:
        by_severity: dict[str, list] = {}
        for v in violations:
            by_severity.setdefault(v["severity"], []).append(v)
        for sev in ("critical", "high", "medium", "low"):
            items = by_severity.get(sev, [])
            if not items:
                continue
            print(f"    {sev.upper()} ({len(items)}):")
            for v in items:
                ts = v["timestamp"].strftime("%H:%M:%S")
                print(f"      [{ts}] {v['type']}: {v['description']}")
    else:
        print("    No violations detected")

    # Detection stats
    print(f"\n  Total draw_box annotations: {state['total_detections']}")
    print("=" * 60)
    print()


if __name__ == "__main__":
    Runner(AgentLauncher(create_agent=create_agent, join_call=join_call)).cli()
