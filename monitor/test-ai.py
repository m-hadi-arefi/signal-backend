import requests
import json

url = "http://claude-gateway:8000/parse"

payload = json.dumps({
  "prompt": "#LYN/USDT BUY SETUP LYN is forming a strong triple bottom pattern and looks ready for an upward move. Momentum is building, and bulls are stepping in 🚀"
})
headers = {
  'Content-Type': 'application/json'
}

response = requests.request("POST", url, headers=headers, data=payload)

print(response.text)
