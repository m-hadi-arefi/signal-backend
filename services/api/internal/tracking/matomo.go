package tracking

import (
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"time"
)

type MatomoClient struct {
	siteID  string
	baseURL string
	token   string
	enabled bool
	client  *http.Client
}

func NewMatomoClient(baseURL, siteID, token string, enabled bool) *MatomoClient {
	return &MatomoClient{
		siteID:  siteID,
		baseURL: baseURL,
		token:   token,
		enabled: enabled,
		client:  &http.Client{Timeout: 3 * time.Second},
	}
}

func (m *MatomoClient) IsEnabled() bool {
	return m.enabled
}

// Track sends a fire-and-forget hit to Matomo for an API request.
// Never blocks the caller — runs in a goroutine.
func (m *MatomoClient) Track(path, method, clientIP, userAgent string, statusCode int) {
	if !m.enabled {
		return
	}
	go func() {
		defer func() { recover() }() // never crash the server if Matomo is unreachable
		params := url.Values{}
		params.Set("idsite", m.siteID)
		params.Set("rec", "1")
		params.Set("apiv", "1")
		params.Set("url", fmt.Sprintf("http://signal-api%s", path))
		params.Set("action_name", fmt.Sprintf("%s %s", method, path))
		params.Set("e_c", "api")
		params.Set("e_a", method)
		params.Set("e_n", path)
		params.Set("e_v", strconv.Itoa(statusCode))
		params.Set("send_image", "0")
		if clientIP != "" {
			params.Set("cip", clientIP)
		}
		if userAgent != "" {
			params.Set("ua", userAgent)
		}
		if m.token != "" {
			params.Set("token_auth", m.token)
		}
		_, _ = m.client.PostForm(m.baseURL+"/matomo.php", params)
	}()
}
