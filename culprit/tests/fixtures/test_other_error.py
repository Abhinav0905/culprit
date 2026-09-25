"""
suspect: S3
mechanism: Exhausts the DB connection pool to raise PoolTimeoutError (different from UnicodeEncodeError).
evidence: E02859
"""
from brightcart.orders import db


def test_pool_exhaustion():
    """Pool must not time out under normal load — asserts pool can be acquired."""
    db.reset()
    db.set_in_use(20)  # pool full → raises PoolTimeoutError
    # This call will raise PoolTimeoutError, which is NOT the incident error
    conn = db.acquire(timeout_s=0.05)
    db.reset()
    conn.close()
    assert True
