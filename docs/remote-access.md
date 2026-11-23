# Reaching your server away from home

> **Not verified by the maintainers on every platform.** Follow the linked official documentation;
> if a step differs from what you see, trust the official docs and please open an issue.

The API token is a bearer secret. Over plain HTTP on the Internet anyone on the path can read it, so
away from home use an encrypted channel. Two options:

## A. Tailscale (recommended: no domain, no open ports)

[Tailscale](https://tailscale.com/kb) puts your devices on a private encrypted network.

1. Install Tailscale on the computer that runs Annona and on your phone; log in with the same account
   ([quickstart](https://tailscale.com/kb/1017/install)).
2. Note the computer's tailnet name or `100.x.y.z` address (shown in the Tailscale app).
3. In the Annona app use `http://<that-address>:8000`. Traffic between your devices is encrypted by
   Tailscale itself, so plain HTTP inside the tailnet is acceptable.
4. Do not publish the port (no router port-forwarding, no Tailscale Funnel).

## B. Your own domain with HTTPS (Caddy)

For a public address. You need a domain pointing to your server and ports 80/443 open.
[Caddy](https://caddyserver.com/docs/) obtains certificates automatically. Example `Caddyfile`:

```
annona.example.com {
    reverse_proxy localhost:8000
}
```

Then use `https://annona.example.com` in the app. Keep the token long and random: the server limits
wrong attempts (10 per minute per address) but is then exposed to the Internet; keep it updated.
Behind a proxy the server sees the proxy's address, so the limit is shared by all clients.
