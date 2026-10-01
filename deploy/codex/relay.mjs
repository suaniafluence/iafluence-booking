import net from "node:net";

const listenPort = Number(process.env.CODEX_PORT || 4500);
const upstreamPort = Number(process.env.CODEX_INTERNAL_PORT || 4501);
const maxHeaderBytes = 64 * 1024;

const server = net.createServer((client) => {
  let request = Buffer.alloc(0);

  const fail = () => client.destroy();
  client.on("error", () => {});

  const readHeaders = (chunk) => {
    request = Buffer.concat([request, chunk]);
    const headerEnd = request.indexOf("\r\n\r\n");
    if (headerEnd === -1) {
      if (request.length > maxHeaderBytes) fail();
      return;
    }

    client.off("data", readHeaders);
    client.pause();
    const headers = request.subarray(0, headerEnd + 4).toString("latin1");
    const body = request.subarray(headerEnd + 4);
    // app-server deliberately accepts loopback HTTP/WebSocket requests only. The
    // Docker-facing socket is merely a private transport, so present its loopback
    // address to app-server while preserving every other header (including auth).
    const loopbackHeaders = headers.replace(/^Host:[^\r]*$/im, `Host: 127.0.0.1:${upstreamPort}`);
    const upstream = net.createConnection({ host: "127.0.0.1", port: upstreamPort });
    upstream.on("error", fail);
    upstream.on("connect", () => {
      upstream.write(loopbackHeaders, "latin1");
      if (body.length) upstream.write(body);
      client.pipe(upstream);
      upstream.pipe(client);
      client.resume();
    });
  };

  client.on("data", readHeaders);
});

server.on("error", (error) => {
  console.error(`codex relay failed: ${error.message}`);
  process.exit(1);
});
server.listen(listenPort, "0.0.0.0", () => {
  console.log(`codex relay listening on 0.0.0.0:${listenPort} -> 127.0.0.1:${upstreamPort}`);
});
