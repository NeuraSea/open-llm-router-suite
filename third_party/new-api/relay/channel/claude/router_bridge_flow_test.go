package claude

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/QuantumNous/new-api/constant"
	relaycommon "github.com/QuantumNous/new-api/relay/common"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

func TestRouterSyncedClaudeChannelTargetsBridgeWithInternalKey(t *testing.T) {
	t.Parallel()

	gin.SetMode(gin.TestMode)
	recorder := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(recorder)
	ctx.Request = httptest.NewRequest(http.MethodPost, "/v1/messages", nil)
	ctx.Request.Header.Set("Content-Type", "application/json")

	info := &relaycommon.RelayInfo{
		OriginModelName: "claude-sonnet-4-6",
		ChannelMeta: &relaycommon.ChannelMeta{
			ApiKey:         "router-bridge-secret",
			ChannelBaseUrl: "http://app:8000/bridge/upstreams/credentials/cred-router/anthropic",
			ChannelType:    constant.ChannelTypeAnthropic,
		},
	}

	adaptor := &Adaptor{}
	requestURL, err := adaptor.GetRequestURL(info)
	require.NoError(t, err)
	require.Equal(t, "http://app:8000/bridge/upstreams/credentials/cred-router/anthropic/v1/messages", requestURL)

	headers := http.Header{}
	require.NoError(t, adaptor.SetupRequestHeader(ctx, &headers, info))
	require.Equal(t, "router-bridge-secret", headers.Get("x-api-key"))
	require.Equal(t, "2023-06-01", headers.Get("anthropic-version"))
	require.Equal(t, "application/json", headers.Get("Content-Type"))
}
