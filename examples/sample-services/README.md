# Sample service definitions

Create via the UI (Services -> Add service) or the API (ADMIN role):

```bash
curl -sS -X POST http://localhost:8080/api/v1/services \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "$(jq '.[0]' examples/sample-services/services.json)"
```

Hostnames above are placeholders; replace them with your own. Service checks cannot target
link-local / cloud-metadata addresses (SSRF guard).
