# x402: pay per video with a wallet

Treza sells single videos over [x402](https://docs.x402.org/). You POST a prompt, the endpoint answers `402 Payment Required` with the exact price, your wallet pays it in USDC on Base or Solana, and the same request returns the video. There is no Treza account, API key or signup. The payment is the only credential.

The full example is **[treza-labs/x402-video-example](https://github.com/treza-labs/x402-video-example)**. It also covers paying on Solana, animating your own picture, reference images, and the speech, music, picture, clip and Short endpoints.

## The short version

[`buy-video.ts`](buy-video.ts) is about 20 lines. It buys one 5 second clip on the endpoint's default model and saves `video.mp4`:

```ts
import { writeFile } from "node:fs/promises";
import { wrapFetchWithPaymentFromConfig } from "@x402/fetch";
import { ExactEvmScheme } from "@x402/evm";
import { privateKeyToAccount } from "viem/accounts";

const wallet = privateKeyToAccount(process.env.PRIVATE_KEY as `0x${string}`); // a small hot wallet holding USDC on Base
const pay = wrapFetchWithPaymentFromConfig(fetch, {
  schemes: [{ network: "eip155:8453", client: new ExactEvmScheme(wallet) }],
  spendControls: { maxAmountPerPayment: "$1" }, // the default 5 s clip is $0.42
});

const res = await pay(process.env.X402_VIDEO_ENDPOINT ?? "https://www.trezalabs.com/api/x402/video", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ prompt: "a paper boat drifting down a rain-filled gutter at dawn", aspectRatio: "9:16" }),
});
if (!res.ok) throw new Error(`Purchase failed (${res.status}): ${await res.text()}`);
const order = await res.json(); // answers within 45 s: the video, or status "running" and a statusUrl
let status = order;
while (status.status === "running") {
  await new Promise((r) => setTimeout(r, status.pollAfterMs ?? 15_000));
  status = await (await fetch(order.statusUrl)).json(); // polling is free: the render is paid for
}
if (!status.video) throw new Error(`No video (${status.status}). ${status.message ?? ""} ${status.retryUrl ?? ""}`);
await writeFile("video.mp4", Buffer.from(await (await fetch(status.video)).arrayBuffer()));
console.log(`Paid $${order.paidUsd} USDC for ${order.seconds}s on ${order.model}. Saved video.mp4`);
```

```bash
npm install @x402/fetch @x402/evm viem tsx
PRIVATE_KEY=0x... npx tsx buy-video.ts
```

## Cost

The 402 challenge quotes the price before any money moves. The default clip, 5 seconds on Hailuo 3 (`minimax-h3`), is $0.42 in USDC. Other models and lengths run from $0.28 (4 seconds on `veo-3.1-lite`) to $4.90. `GET https://www.trezalabs.com/api/x402/video` lists them with their prices.

`maxAmountPerPayment` is the most one payment may be. The snippet sets $1, enough for the default clip. Raise it for longer clips or other models.

Use a small, dedicated wallet, never a main one. It needs USDC on Base and nothing else: the payment is a signed transfer authorization, so there is no gas to pay in ETH.

## Expected output

```
Paid $0.42 USDC for 5s on minimax-h3. Saved video.mp4
```

The paid request waits up to 45 seconds for the render. A longer render comes back with `"status": "running"` and a `statusUrl`, which the snippet polls until the video is ready. If a render fails, the payment stays as credit for that wallet, and the answer's `retryUrl` renders again without paying twice.

## With an account instead

If you have a Treza account and credits, the other recipes here use your API key and prepaid balance instead of a wallet.
