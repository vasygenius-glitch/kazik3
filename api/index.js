const https = require('https');

module.exports = (req, res) => {
  // Handle root health check
  if (req.url === '/' || req.url === '/health') {
    res.statusCode = 200;
    res.setHeader('Content-Type', 'application/json');
    return res.end(JSON.stringify({ status: "🟢 Telegram Proxy Active", target: "api.telegram.org" }));
  }

  const options = {
    hostname: 'api.telegram.org',
    port: 443,
    path: req.url,
    method: req.method,
    headers: { ...req.headers }
  };
  
  // Remove host header to avoid SSL certificate issues
  delete options.headers.host;
  delete options.headers.connection;

  const proxyReq = https.request(options, (proxyRes) => {
    res.statusCode = proxyRes.statusCode;
    for (const [key, value] of Object.entries(proxyRes.headers)) {
      res.setHeader(key, value);
    }
    proxyRes.pipe(res);
  });

  proxyReq.on('error', (err) => {
    res.statusCode = 502;
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({ ok: false, error_code: 502, description: `Proxy Error: ${err.message}` }));
  });

  req.pipe(proxyReq);
};

module.exports.config = {
  api: {
    bodyParser: false,
  },
};
