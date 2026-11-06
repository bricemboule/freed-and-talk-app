from fastapi import Request, HTTPException
from app.core.config import get_settings

# All deployments must use Redis. Local standalone development can disable the
# limiter if Redis isn't configured; production startup rejects missing Redis.
_client = None

def rate_limit(request: Request, action: str, key: str, limit: int, window: int):
    global _client
    config=get_settings()
    if not config.redis_url:
        return
    if _client is None:
        import redis
        _client=redis.Redis.from_url(config.redis_url, socket_timeout=2)
    address=request.client.host if request.client else 'unknown'
    # One limiter per IP plus account/challenge identifier. Do not include raw email.
    from hashlib import sha256
    digest=sha256(key.encode()).hexdigest()[:24]
    for scope in (f'ip:{address}',f'key:{digest}'):
        bucket=f'auth:{action}:{scope}'
        try:
            count=_client.incr(bucket)
            if count==1:
                _client.expire(bucket,window)
            if count>limit:
                raise HTTPException(429,detail={'code':'RATE_LIMIT_EXCEEDED','message':'Too many requests'})
        except HTTPException:
            raise
        except Exception:
            if config.app_env=='production':
                raise HTTPException(503,detail={'code':'RATE_LIMIT_UNAVAILABLE','message':'Rate limit service unavailable'})
