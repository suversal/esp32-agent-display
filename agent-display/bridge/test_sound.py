"""Explicitly audition the device's two sounds, including during bridge quiet hours."""
import argparse
import asyncio
import aiohttp
async def run(url, kind):
    sounds = ("urgent", "soft") if kind == "both" else (kind,)
    async with aiohttp.ClientSession() as client:
        for sound in sounds:
            async with client.post(url + "/debug/sound", json={"sound": sound}) as response:
                response.raise_for_status()
                result = await response.json()
                if not result["delivered"]:
                    raise RuntimeError("No firmware 0.2.0 device connected.")
                print(f"MANUAL_SOUND_SENT kind={sound} devices={result['delivered']}", flush=True)
            await asyncio.sleep(2)
parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8787")
parser.add_argument("--sound", choices=("urgent", "soft", "both"), default="both")
args = parser.parse_args()
asyncio.run(run(args.url, args.sound))
