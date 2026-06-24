const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');

const app = express();
const PORT = process.env.PORT || 3000;

// Health check route for Render
app.get('/health', (req, res) => {
  res.status(200).send('OK');
});

// Proxy route to forward requests to Telegram Bot API
app.use('/', createProxyMiddleware({
  target: 'https://api.telegram.org',
  changeOrigin: true,
  onProxyReq: (proxyReq, req, res) => {
    // Remove host header to avoid SSL verification / mismatch issues
    proxyReq.removeHeader('host');
  },
  logLevel: 'info'
}));

app.listen(PORT, () => {
  console.log(`Telegram Proxy running on port ${PORT}`);
});
