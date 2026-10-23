// Demo target app for the Liara assistant.
// It has routes that create problems on purpose, for diagnosis demos.
const express = require("express");
const app = express();
const PORT = process.env.PORT || 3000;

// Memory that we keep on purpose to simulate a memory leak.
const leak = [];

// Write one log line for each request.
app.use((req, res, next) => {
  console.log(`[request] ${req.method} ${req.url}`);
  next();
});

app.get("/", (req, res) => res.send("Target app is running."));

app.get("/health", (req, res) => {
  const memMb = Math.round(process.memoryUsage().rss / 1024 / 1024);
  res.json({ status: "ok", memory_mb: memMb, leak_chunks: leak.length });
});

// Scenario 1: an application error that gives HTTP 500.
app.get("/error", (req, res) => {
  try {
    const order = undefined;
    order.total; // This line throws a TypeError on purpose.
  } catch (err) {
    console.error(`[error] /error failed: ${err.stack}`);
    res.status(500).send("Internal Server Error");
  }
});

// Scenario 2: a missing environment variable gives HTTP 500.
// Fix: set GREETING in the app settings (a config change that needs approval).
app.get("/greet", (req, res) => {
  if (!process.env.GREETING) {
    console.error("[error] GREETING environment variable is not set");
    return res.status(500).send("Configuration error");
  }
  res.send(process.env.GREETING);
});

// Scenario 3: a memory leak. Each call keeps about 20 MB more.
app.get("/leak", (req, res) => {
  leak.push(Buffer.alloc(20 * 1024 * 1024, 1));
  const memMb = Math.round(process.memoryUsage().rss / 1024 / 1024);
  console.warn(`[warn] memory grew to ${memMb} MB (chunks: ${leak.length})`);
  res.send(`Memory now: ${memMb} MB`);
});

// Scenario 4: high CPU. The request blocks the CPU for the given time.
app.get("/cpu", (req, res) => {
  const ms = Math.min(Number(req.query.ms) || 5000, 30000);
  const end = Date.now() + ms;
  while (Date.now() < end) { /* busy loop on purpose */ }
  console.warn(`[warn] CPU busy for ${ms} ms`);
  res.send(`CPU was busy for ${ms} ms`);
});

app.listen(PORT, () => console.log(`[start] listening on port ${PORT}`));
