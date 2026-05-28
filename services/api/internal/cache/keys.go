package cache

import (
	"fmt"
	"strings"
)

// SignalsListCacheKey builds a deterministic cache key for paginated signal list queries.
// Each unique combination of (page, limit, symbol, srcType, srcProvider) gets its own key.
func SignalsListCacheKey(page, limit int, symbol, srcType, srcProvider string) string {
	parts := []string{
		fmt.Sprintf("p:%d", page),
		fmt.Sprintf("l:%d", limit),
	}
	if symbol != "" {
		parts = append(parts, "sym:"+symbol) // already uppercased by handler
	}
	if srcType != "" {
		parts = append(parts, "type:"+srcType)
	}
	if srcProvider != "" {
		parts = append(parts, "prov:"+srcProvider)
	}
	return "signals:list:" + strings.Join(parts, ":")
}

// SignalsResultsCacheKey is the results-variant — includes scenarios + scenario_results payload.
func SignalsResultsCacheKey(page, limit int, symbol, srcType, srcProvider string) string {
	key := SignalsListCacheKey(page, limit, symbol, srcType, srcProvider)
	return strings.Replace(key, "signals:list:", "signals:results:", 1)
}
