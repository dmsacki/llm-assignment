import requests, sys

url = 'http://localhost:8000/ask'
payload = {'question': 'What are the library hours?'}
try:
    r = requests.post(url, json=payload, timeout=35)
    print('STATUS', r.status_code)
    try:
        print(r.json())
    except Exception:
        print(r.text)
except Exception as e:
    print('EXCEPTION', repr(e))
    sys.exit(0)
