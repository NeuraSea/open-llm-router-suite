package codex

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/QuantumNous/new-api/constant"
	"github.com/QuantumNous/new-api/dto"
	relaycommon "github.com/QuantumNous/new-api/relay/common"
	relayconstant "github.com/QuantumNous/new-api/relay/constant"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

func TestRouterSyncedCodexChannelBuildsResponsesDownstreamRequest(t *testing.T) {
	t.Parallel()

	gin.SetMode(gin.TestMode)
	recorder := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(recorder)
	ctx.Request = httptest.NewRequest(http.MethodPost, "/v1/responses", nil)
	ctx.Request.Header.Set("Content-Type", "application/json")

	info := &relaycommon.RelayInfo{
		RelayMode:       relayconstant.RelayModeResponses,
		OriginModelName: "gpt-5.4",
		ChannelMeta: &relaycommon.ChannelMeta{
			ApiKey:         `{"access_token":"router-bound-access","refresh_token":"router-bound-refresh","account_id":"acct-router","type":"codex"}`,
			ChannelBaseUrl: "https://chatgpt.com",
			ChannelType:    constant.ChannelTypeCodex,
		},
	}

	adaptor := &Adaptor{}
	converted, err := adaptor.ConvertOpenAIResponsesRequest(ctx, info, dto.OpenAIResponsesRequest{
		Model: "gpt-5.4",
		Input: json.RawMessage(`[{"role":"user","content":"Reply with OK"}]`),
	})
	require.NoError(t, err)
	request := converted.(dto.OpenAIResponsesRequest)
	require.JSONEq(t, `""`, string(request.Instructions))
	require.JSONEq(t, `false`, string(request.Store))
	require.Nil(t, request.MaxOutputTokens)

	requestURL, err := adaptor.GetRequestURL(info)
	require.NoError(t, err)
	require.Equal(t, "https://chatgpt.com/backend-api/codex/responses", requestURL)

	headers := http.Header{}
	require.NoError(t, adaptor.SetupRequestHeader(ctx, &headers, info))
	require.Equal(t, "Bearer router-bound-access", headers.Get("Authorization"))
	require.Equal(t, "acct-router", headers.Get("chatgpt-account-id"))
	require.Equal(t, "responses=experimental", headers.Get("OpenAI-Beta"))
	require.Equal(t, "codex_cli_rs", headers.Get("originator"))
	require.Equal(t, "application/json", headers.Get("Content-Type"))
	require.Equal(t, "application/json", headers.Get("Accept"))
}
