import pgserver, time, sys
s = pgserver.get_server('/tmp/pgsc', cleanup_mode=None)
print('PG_UP', s.get_uri(), flush=True)
while True: time.sleep(3600)
