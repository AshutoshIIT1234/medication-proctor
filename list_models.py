import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))

print("Listing models...")
try:
    for m in client.models.list():
        if "gemini" in m.name:
            print(f"Name: {m.name}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
