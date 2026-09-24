#!/usr/bin/env bash
# Show the biggest memory consumers on gx10 (human readable).
echo "=== top RSS processes ==="
ps -eo pid,rss,comm --sort=-rss | head -15 | while read pid rss comm; do
  printf "%-8s %-20s %6.1f GB\n" "$pid" "$comm" "$(echo "$rss/1048576" | bc -l)"
done
echo
echo "=== docker container memory ==="
for c in $(docker ps -q); do
  name=$(docker inspect -f '{{.Name}}' "$c" | sed 's#^/##')
  stats=$(docker stats --no-stream --format '{{.MemUsage}}' "$c" 2>/dev/null)
  printf "%-22s %s\n" "$name" "$stats"
done
echo
echo "=== system memory ==="
free -g | head -2
