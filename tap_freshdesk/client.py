import time
import collections
import functools
import backoff
import requests
import singer


LOGGER = singer.get_logger()
BASE_URL = "https://{}.freshdesk.com"


def ratelimit(limit, every):
    """
    Keeps minimum seconds(every) of time between two request calls.
    """
    def limitdecorator(fn):
        times = collections.deque()

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if len(times) >= limit:
                t0 = times.pop()    # Takes last call time
                t = time.time()     # current time
                sleep_time = every - (t - t0)   # If difference is < every(time)
                if sleep_time > 0:              # Sleep for remaining time
                    time.sleep(sleep_time)

            times.appendleft(time.time())   # Appending current time to list
            return fn(*args, **kwargs)

        return wrapper

    return limitdecorator

class FreshdeskClient:
    """
    The client class is used for making REST calls to the Freshdesk API.
    """

    def __init__(self, config):
        self.config = config
        self.session = requests.Session()
        self.base_url = BASE_URL.format(config.get("domain"))

    def __enter__(self):
        self.check_access_token()
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        # Kill the session instance.
        self.session.close()

    def check_access_token(self):
        """
        Check if the access token is valid.
        """
        self.request(self.base_url+"/api/v2/roles", {"per_page": 1, "page": 1})

    @backoff.on_exception(backoff.expo,
                          (requests.exceptions.RequestException),
                          max_tries=5,
                          giveup=lambda e: e.response is not None and 400 <= e.response.status_code < 500,
                          factor=2)
    @ratelimit(1, 2)
    def request(self, url, params=None):
        """
        Call rest API and return the response in case of status code 200.
        """
        headers = {}
        if 'user_agent' in self.config:
            headers['User-Agent'] = self.config['user_agent']

        req = requests.Request('GET', url, params=params, auth=(self.config['api_key'], ""), headers=headers).prepare()
        LOGGER.info("GET %s", req.url)
        response = self.session.send(req)

        # Call the function again if the rate limit is exceeded
        if 'Retry-After' in response.headers:
            retry_after = int(response.headers['Retry-After'])
            LOGGER.info("Rate limit reached. Sleeping for %s seconds", retry_after)
            time.sleep(retry_after)
            return self.request(url, params)

        response.raise_for_status()

        return response.json()
