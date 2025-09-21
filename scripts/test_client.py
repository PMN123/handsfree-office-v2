import asyncio, websockets, json

async def main():
    ws = await websockets.connect("ws://127.0.0.1:8765")
    tests = [
        "open gmail",
        "type hello judges this is handsfree office",
        "open twitter.com",
        "open chrome",
        "start presentation",
        "next slide",
        "scroll down"
    ]
    for t in tests:
        await ws.send(json.dumps({"type":"command","text":t}))
        print(t, "→", await ws.recv())
    await ws.close()

asyncio.run(main())