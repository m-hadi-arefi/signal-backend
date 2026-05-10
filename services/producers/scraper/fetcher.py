import requests
def fetch(url: str): 
    response = requests.get( url, timeout=10, headers={ "User-Agent": "Mozilla/5.0" } ) 
    response.raise_for_status() 
    return response.text