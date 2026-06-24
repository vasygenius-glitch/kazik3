const https = require('https');

module.exports = (req, res) => {
  const options = {
    hostname: 'api.telegram.org',
    port: 443,
    path: req.url,
    method: req.method,
    headers: { ...req.headers }
  };
  
  // Remove host header to avoid SSL certificate issues
  if (options.headers.host) {
    delete options.headers.host;
  }

  const proxyReq = https.request(options, (proxyRes) => {
    // Set status code
    res.statusCode = proxyRes.statusCode;
    
    // Copy headers
    for (const [key, value] of Object.entries(proxyRes.headers)) {
      res.setHeader(key, value);
    }
    
    // Pipe response
    proxyRes.pipe(res);
  });

  proxyReq.on('error', (err) => {
    res.statusCode = 502;
    res.end(`Proxy Error: ${err.message}`);
  });

  // Pipe request body
  req.pipe(proxyReq);
};
