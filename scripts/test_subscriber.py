import asyncio, websockets
async def main():
    async with websockets.connect("ws://localhost:8765") as ws:
        while True:
            print(await ws.recv())
asyncio.run(main())