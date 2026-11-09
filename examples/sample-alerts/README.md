# Sample Alertmanager webhook payload

Send it to a running backend to see an incident appear (replace the token with your own
`IGUARD_WEBHOOK_TOKEN`; never commit real tokens):

```bash
curl -sS -X POST http://localhost:8080/api/v1/alerts/webhook \
  -H "Authorization: Bearer $IGUARD_WEBHOOK_TOKEN" -H "Content-Type: application/json" \
  --data @examples/sample-alerts/alertmanager-webhook.json
```
