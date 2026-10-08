import requests

url = "https://m.avito.ru/moskva/avtomobili/kia/rio-ASgBAgICAkTgtg3KmCjitg3Krig?context=H4sIAAAAAAAA_wGeAGH_YTo0OntzOjk6ImZyb21fcGFnZSI7czo3OiJmaWx0ZXJzIjtzOjY6InNvdXJjZSI7czo4OiJvcmRpbmFyeSI7czo1Mjoic291cmNlX3F1ZXJ5IjtzOjc6ImtpYSByaW8iO3M6NToieF9zZ3QiO3M6NDA6IjM4MDNiMzU2Mzk1ZDIwMDk4NjY3Y2IzMzliMGRhZjkzZTcxYzNlODMiO32uyOswngAAAA&f=ASgBAgECAkTgtg3KmCjitg3KrigDRf4pGXsiZnJvbSI6bnVsbCwidG8iOjIwMDAwMH3GmgwWeyJmcm9tIjowLCJ0byI6NzAwMDAwffqMFBd7ImZyb20iOjIwMTYsInRvIjpudWxsfQ&moreExpensive=0&presentationType=serp&radius=0"

headers = {
    "User-Agent": "Mozilla/5.0"
}

response = requests.get(
    url,
    headers=headers,
    timeout=20
)

print("STATUS:", response.status_code)
print("LENGTH:", len(response.text))
print(response.text[:1000])
