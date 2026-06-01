package cache

import (
	"fmt"
	"strings"
)

// KeySignals builds a deterministic cache key for paginated signal lists.
func KeySignals(page, limit int, symbol, provider string) string {
	parts := []string{
		fmt.Sprintf("p:%d", page),
		fmt.Sprintf("l:%d", limit),
	}
	if symbol != "" {
		parts = append(parts, "sym:"+strings.ToUpper(symbol))
	}
	if provider != "" {
		parts = append(parts, "prov:"+provider)
	}
	return "sig:list:" + strings.Join(parts, ":")
}

// KeySignalByID builds a cache key for a single signal.
func KeySignalByID(id int64) string {
	return fmt.Sprintf("sig:id:%d", id)
}

// KeySources builds the cache key for the sources list.
func KeySources() string {
	return "sig:sources"
}

// KeyActiveCoins builds the cache key for the active coins list.
func KeyActiveCoins() string {
	return "sig:coins:active"
}
