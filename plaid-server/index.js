/**
 * Minimal Plaid Link server for Portfolio 360.
 *
 * Handles the full OAuth flow in a real browser tab, then writes the result
 * to ../data/plaid_result.json so Streamlit can pick it up.
 *
 * Usage:
 *   cd plaid-server && npm install && node index.js
 *   Then open http://localhost:3001 in your browser.
 */
require("dotenv").config({ path: "../.env" });

const express = require("express");
const { Configuration, PlaidApi, PlaidEnvironments, Products, CountryCode } = require("plaid");
const fs = require("fs");
const path = require("path");

const PORT = 3001;
const RESULT_FILE = path.join(__dirname, "../data/plaid_result.json");

const plaidEnv = process.env.PLAID_ENV || "production";
const envMap = {
  sandbox: PlaidEnvironments.sandbox,
  development: PlaidEnvironments.development,
  production: PlaidEnvironments.production,
};

const client = new PlaidApi(
  new Configuration({
    basePath: envMap[plaidEnv] || PlaidEnvironments.production,
    baseOptions: {
      headers: {
        "PLAID-CLIENT-ID": process.env.PLAID_CLIENT_ID,
        "PLAID-SECRET": process.env.PLAID_SECRET,
      },
    },
  })
);

const app = express();
app.use(express.json());

// ── Create link token ─────────────────────────────────────────────────────────
app.get("/create_link_token", async (req, res) => {
  try {
    const resp = await client.linkTokenCreate({
      user: { client_user_id: "local-user" },
      client_name: "Big Casino",
      products: [Products.Transactions],
      optional_products: [Products.Investments, Products.Liabilities],
      country_codes: [CountryCode.Us],
      language: "en",
    });
    res.json({ link_token: resp.data.link_token });
  } catch (err) {
    console.error("link_token_create failed:", err.response?.data || err.message);
    res.status(500).json({ error: String(err.message) });
  }
});

// ── Exchange public token ─────────────────────────────────────────────────────
app.post("/exchange_token", async (req, res) => {
  const { public_token, institution } = req.body;
  try {
    const resp = await client.itemPublicTokenExchange({ public_token });
    const result = {
      item_id: resp.data.item_id,
      access_token: resp.data.access_token,
      institution: institution || "Unknown",
      created_at: new Date().toISOString(),
    };
    fs.mkdirSync(path.dirname(RESULT_FILE), { recursive: true });
    fs.writeFileSync(RESULT_FILE, JSON.stringify(result, null, 2));
    console.log(`Saved Plaid result for ${institution} → ${RESULT_FILE}`);
    res.json({ ok: true });
  } catch (err) {
    console.error("exchange failed:", err.response?.data || err.message);
    res.status(500).json({ error: String(err.message) });
  }
});

// ── Plaid Link UI ─────────────────────────────────────────────────────────────
app.get("/", (req, res) => {
  res.send(`<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Connect account — Portfolio 360</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #111; color: #eee; font-family: -apple-system, sans-serif;
           display: flex; flex-direction: column; align-items: center;
           justify-content: center; height: 100vh; gap: 16px; }
    h1 { font-size: 22px; font-weight: 600; }
    p  { font-size: 14px; color: #999; max-width: 360px; text-align: center; }
    button { background: #f0a500; color: #111; border: none; border-radius: 8px;
             padding: 12px 28px; font-size: 16px; font-weight: 700; cursor: pointer; }
    button:disabled { opacity: 0.5; cursor: default; }
    #status { font-size: 14px; color: #aaa; min-height: 20px; }
    #status.success { color: #4caf50; }
    #status.error   { color: #f44336; }
  </style>
</head>
<body>
  <h1>Portfolio <span style="color:#f0a500">·</span> 360°</h1>
  <p>Click the button to open Plaid Link and connect your financial institution.</p>
  <button id="btn" onclick="startLink()">Connect account</button>
  <div id="status"></div>

  <script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
  <script>
    var handler = null;

    async function startLink() {
      document.getElementById('btn').disabled = true;
      setStatus('Loading…', '');
      try {
        const r = await fetch('/create_link_token');
        const { link_token, error } = await r.json();
        if (error) throw new Error(error);

        handler = Plaid.create({
          token: link_token,
          onSuccess: async function(public_token, metadata) {
            setStatus('Saving…', '');
            const inst = metadata.institution?.name || 'Unknown';
            try {
              const ex = await fetch('/exchange_token', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ public_token, institution: inst }),
              });
              const { ok, error } = await ex.json();
              if (!ok) throw new Error(error);
              setStatus('✓ Connected! Switch back to Portfolio 360 and click Finish connecting.', 'success');
            } catch (e) {
              setStatus('Exchange failed: ' + e.message, 'error');
              document.getElementById('btn').disabled = false;
            }
          },
          onExit: function(err) {
            document.getElementById('btn').disabled = false;
            if (err) setStatus('Error: ' + (err.display_message || err.error_message), 'error');
            else setStatus('', '');
          },
        });
        handler.open();
      } catch (e) {
        setStatus('Error: ' + e.message, 'error');
        document.getElementById('btn').disabled = false;
      }
    }

    function setStatus(msg, cls) {
      var el = document.getElementById('status');
      el.textContent = msg;
      el.className = cls;
    }
  </script>
</body>
</html>`);
});

app.listen(PORT, () => {
  console.log(`Plaid server running at http://localhost:${PORT}`);
  console.log(`Using Plaid environment: ${plaidEnv}`);
});
