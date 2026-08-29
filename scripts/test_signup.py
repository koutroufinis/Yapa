import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
url='http://127.0.0.1:5000/api/signup'
data=json.dumps({'email':'alice@example.com','username':'alice_test','password':'password123'}).encode()
req=Request(url, data=data, headers={'Content-Type':'application/json'})
try:
    resp=urlopen(req, timeout=5)
    print('STATUS', resp.getcode())
    print(resp.read().decode())
except HTTPError as e:
    print('HTTP', e.code, e.read().decode())
except URLError as e:
    print('URL', e.reason)
except Exception as e:
    print('EX', e)
