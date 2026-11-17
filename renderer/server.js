// Placeholder. Step 5 turns this into: Site Document -> static HTML.
const http = require("http");
http
  .createServer((req, res) => {
    res.setHeader("content-type", "application/json");
    res.end(JSON.stringify({ service: "renderer", status: "ok" }));
  })
  .listen(4000, "0.0.0.0", () => console.log("renderer listening on :4000"));
