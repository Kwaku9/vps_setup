"""Replay captured voice audio through LiteLLM to test Gemini response.

Run with the key in the environment, never inline:
    LITELLM_API_KEY=... python3 test_voice_replay.py
"""
import asyncio
import json
import base64
import os
import sys

import websockets

# First chunk from the captured audio (real voice, ~40ms of PCM at 16kHz)
VOICE_CHUNKS = [
    "AHwAXABIAEgALAAgABwAFAAUAAAD8//r/9f/z//P/8P/q/+v/7v/v//b//f8CAAEAAAD7//n/9v/2//X/+P8DAAoACwARABAADgAOAAYAAQD7//j/9v/0//b/8P/s/+v/6//j/+P/5//q//D/+P8BAP//AgAAAPr/7//r/+v/5//p/+z/7//q/+T/3//e/9n/0P/J/83/z//P/8n/wf+9/8D/v/+7/77/zf/d/+3///8JABIAJAA3AEIATwBWAGAAZgBrAHEAbgBtAGgAZwBaAE0APgAyAC0AKAAqACYAJwApACkAHgATAAsA+f/x/+j/4v/h/+L/6f/v//b/9f/1//r/+P/5//v/AQAHAA0AEwAcACMAKgAzADUAOQA5AC8AJAAkACMAIwAgACUAJgAjAB8AGAASAAcABAD+/////v/5/w==",
    "4P/N/9T/0//W/93/4v/i/+H/5f/r//H/8f/x//D/7//p/+X/4v/l/+v/6//o/+3/9f/6//z/AAAIAAsAEwAWABIAEgANAAoACgAEAP7/+f/4//j/8//w//P/6f/k/+b/5//l/+P/4v/i/+X/5v/l/+H/4//l/+P/3//f/+X/6f/q/+z/9f/0//L/8f/2//j/+P/8//3/+/8BAAUA/f/0/+7/6//l/+P/3P/W/9j/5v/p/+b/7v/2//H/4v/Z/9H/1f/k/+//4f/c/+D/6P/q/+b/6P/q//L/9v/1//v/BgAIAAoADgAQABAAFgAWABAADgAZAB0ACwAHAAkADgAOABQADAAHAAwADQALAAcADAAUAB0AGAARABUAEQAQAAwA/f/0//r/CAANAA0ACgANABQAEQAHAP///v/6/woAEwANAA4AHgAlABwADwAJAAAAAwANAA0AEQAZACsAMQAyAC0ALQAtACYAHwAXABAABgASABoAFgAYABwAFQALAAkA/f/6//T//f/7//b/+P8HAAQA9v/2//T/6v/j/+P/2//k//f/BQAMAA8AFAATABMACwAFAPz//f8CAAcADwAQABIADwARAAoAAwDy/+r/8////woACwAKAA0AFgATAAkAAgD9/wEADAAOAA4AEAAUABQAEgALAP7/9v/t/+X/5f/u//D/7f/v//L/9//+//X/6f/p//b/+P/0//D/9f8EABcAGAANAAIADAAVABIACQAGAA0AEwAZABMABwD//wsADAAEAPz//P//////+P/t//L/6f/i/9X/1P/O/8f/v/+4/7f/v//H/8P/xf/H/9X/3P/d/93/5v/m/+r/5//t/+3/7//0//H/9P/5//b/7v/0/+//7//v/+7/6v/t//b//P/7//7/CQAHAAUAAwD///f/+f/6/+3/6f/x//n/+f/9////AAD9//j/+//+/wUAEQAYAB4AJAAoACQAFQAIAAgABQACAAIACQAPABYAFQAbABgAFAANAAcA/v/5//f/9v/8//3//v/6//7/+//0//D/7//v//H/9v/2//7//f8EAAQAAQD4//f/+P/6//v/AwANABMAFwASAA0AAgD8//n/9//2//v/9v/8/wMADAANABMAFgAPAAsACgAGAP//BQALAA0AEAANAAkABgAKAA0ACQAMAAwAEwAVABwAHQAWAB0AJQAnABwAGQAUABYADwAQABQAHAAlACUAJQAbABMADgAOAAwACwAKAAYADgASABUAEwAVABoAHQAaABQAFQAWACAAJAAaAA0ADwAQAAgAAgD///7/AgD///3/9v/2//v/9v/v/+j/8f/t/+3/5f/i/+P/5//i/+D/4v/m/+b/5P/c/+L/5//i/9v/2f/g/+X/6v/r/+//9f/8//f/8P/u/+z/6//y//T/8v8BABMAGgAeACYALAAyACwAKwArADAAMAA2ADgAMwA5ADQAKgAZAA4AAwD+//v/+/8AAAEACwALAA8AEwAZABgAFgAbACAAKwAuADAALwAuACkAJQAhABYAEQAOAAsACAAOABoAIgAmACgAKwAyADYAMgAvADAALgAxADEANAAxADMAMQAtACoAIQARAAcAAQD3//L/9P/1//j/+//8//7/+v/8//3//f/9//r/+P/8////AgACAAEAAgD///j/7v/r/+v/8//1//n/+P/7//3//P/7//X/8//y//H/6P/l/+D/4f/d/9T/zv/I/8T/wP+5/7n/sf+q/8P/4v/k/+H/3P/Q/8z/z//L/73/zP/o//7/BAAKACEANwA0ACUADADw/+L/2v/O/7z/pf+d/57/oP+g/6b/r/+4/8T/zf/Z/+L/9/8DAAcAAgD4/+b/1v/P/8T/uP+n/6D/nP+Z/57/nv+b/4z/d/97/5//wf/P/+X/9v/7//f//f/y/93/4f/2//r/9P8UAEQAXwBoAHgAcABjAGcAcQBeAE0AUQBWAEgARABQAEoAQwA7ADEAGgAXABsAHwAbACYAOAA+AEIATABSAEoAQgA3AC4AJAAmACYAGgAQAAgAAwD+//z/+v/w/+//8//1//z/CwAYACkAOgBHAEsASQBHAEIAPQA5ADQAJAAfAB8AGAATAAoABAD///7//v/+//v/AwAMAA8AEgAbACAAJAAtAC4ALgArAC0AJwAcABYAFwASAAsACAADAP//+f/3//D/6P/l/+T/4//l//f/AAAGAAkADAANABAAEAAIAAMA+//2//D/6f/m/+H/3f/c/97/2//f/+P/5f/n/+n/7v/t/+7/5//h/9v/3f/f/9f/0//S/9T/1P/Q/8n/xv/F/8P/vv+7/8H/xP/L/8//zv/P/8//z//S/8n/xv/B/8P/w//G/8z/y//L/83/0f/P/9H/z//P/8r/yv/P/9D/z//T/9z/4//s/+v/7//3/wIABgALABUAFwAaABgAFAAOAAYABQADAAAA/P/8//j/9v/5//v///8DAAQACAAMABAAEQAQAA8ADgAMAAsACgAHAAgACgAKAA4AEwAZABoAIAAfACEAHwAcABYAFAASAA8ADgAKABEAEwAWABIAEwASABAAEgARABEABwAKAAQAAAD+/wQACQANABMAEAATAA8AEAALAAwADAARABIAEAAQAA0ADgANAAsABQAFAAQACAAEAAUAAAD3//z/8//r/+//7f/v//X/7//u//X/9////wAA/////wQABw=="
]

KEY = os.environ.get("LITELLM_API_KEY", "")
if not KEY:
    sys.exit("set LITELLM_API_KEY in the environment (never hardcode it here)")
URI = "ws://127.0.0.1:4000/vertex_ai/live?vertex_project=aicortexi-web-search&vertex_location=us-central1"

async def test():
    headers = {"Authorization": f"Bearer {KEY}"}

    async with websockets.connect(URI, additional_headers=headers, close_timeout=15) as ws:
        # Setup
        await ws.send(json.dumps({
            "setup": {
                "model": "projects/aicortexi-web-search/locations/us-central1/publishers/google/models/gemini-live-2.5-flash-native-audio",
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {"voiceName": "Kore"}
                        }
                    }
                }
            }
        }))

        msg = await asyncio.wait_for(ws.recv(), timeout=10)
        print("Setup OK")

        # Replay captured voice chunks
        for i, chunk in enumerate(VOICE_CHUNKS):
            await ws.send(json.dumps({
                "realtimeInput": {
                    "audio": {
                        "data": chunk,
                        "mimeType": "audio/pcm;rate=16000"
                    }
                }
            }))
            await asyncio.sleep(0.04)

        print(f"Sent {len(VOICE_CHUNKS)} voice chunks")

        # Send silence to trigger end-of-speech detection
        silence = base64.b64encode(b"\x00" * 1280).decode()
        for _ in range(75):
            await ws.send(json.dumps({
                "realtimeInput": {
                    "audio": {
                        "data": silence,
                        "mimeType": "audio/pcm;rate=16000"
                    }
                }
            }))
            await asyncio.sleep(0.04)

        print("Sent silence, waiting for response...")

        # Wait for response
        try:
            for i in range(30):
                msg = await asyncio.wait_for(ws.recv(), timeout=10)
                data = json.loads(msg)
                sc = data.get("serverContent", {})
                parts = sc.get("modelTurn", {}).get("parts", [])
                audio_count = sum(1 for p in parts if "inlineData" in p)
                turn_complete = sc.get("turnComplete", False)
                print(f"  #{i+1}: audio={audio_count}, turnComplete={turn_complete}")
                if turn_complete:
                    break
        except asyncio.TimeoutError:
            print("  No response from Gemini (timeout)")

asyncio.run(test())
