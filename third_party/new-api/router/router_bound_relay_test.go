package router

import (
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/constant"
	"github.com/QuantumNous/new-api/model"
	"github.com/QuantumNous/new-api/service"
	"github.com/QuantumNous/new-api/setting"
	"github.com/QuantumNous/new-api/setting/ratio_setting"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type capturedRelayRequest struct {
	Path   string
	Header http.Header
	Body   string
}

func setupRouterBoundRelayTest(t *testing.T) *gin.Engine {
	t.Helper()

	oldDB := model.DB
	oldLogDB := model.LOG_DB
	oldSQLitePath := common.SQLitePath
	oldRedisEnabled := common.RedisEnabled
	oldMemoryCacheEnabled := common.MemoryCacheEnabled
	oldIsMasterNode := common.IsMasterNode
	oldUsingSQLite := common.UsingSQLite
	oldUsingMySQL := common.UsingMySQL
	oldUsingPostgreSQL := common.UsingPostgreSQL
	oldCountToken := constant.CountToken
	oldGetMediaToken := constant.GetMediaToken
	oldGetMediaTokenNotStream := constant.GetMediaTokenNotStream
	oldModelRatio := ratio_setting.ModelRatio2JSONString()

	t.Cleanup(func() {
		if model.DB != nil {
			if sqlDB, err := model.DB.DB(); err == nil {
				_ = sqlDB.Close()
			}
		}
		model.DB = oldDB
		model.LOG_DB = oldLogDB
		common.SQLitePath = oldSQLitePath
		common.RedisEnabled = oldRedisEnabled
		common.MemoryCacheEnabled = oldMemoryCacheEnabled
		common.IsMasterNode = oldIsMasterNode
		common.UsingSQLite = oldUsingSQLite
		common.UsingMySQL = oldUsingMySQL
		common.UsingPostgreSQL = oldUsingPostgreSQL
		constant.CountToken = oldCountToken
		constant.GetMediaToken = oldGetMediaToken
		constant.GetMediaTokenNotStream = oldGetMediaTokenNotStream
		_ = ratio_setting.UpdateModelRatioByJSONString(oldModelRatio)
		_ = setting.UpdateUserUsableGroupsByJSONString(`{"default":"默认分组","vip":"vip分组"}`)
		_ = ratio_setting.UpdateGroupRatioByJSONString(`{"default":1,"vip":1,"svip":1}`)
	})

	common.SQLitePath = filepath.Join(t.TempDir(), "newapi-router-bound-relay.db")
	common.RedisEnabled = false
	common.MemoryCacheEnabled = false
	common.IsMasterNode = true
	common.UsingSQLite = false
	common.UsingMySQL = false
	common.UsingPostgreSQL = false
	constant.CountToken = false
	constant.GetMediaToken = false
	constant.GetMediaTokenNotStream = false
	t.Setenv("ROUTER_SSO_ENABLED", "true")
	t.Setenv("ROUTER_SSO_ENTERPRISE_GROUP", "enterprise")

	require.NoError(t, ratio_setting.UpdateGroupRatioByJSONString(`{"default":1,"private-u-router":1,"enterprise":1}`))
	require.NoError(t, ratio_setting.UpdateModelRatioByJSONString(`{"gpt-5.4":1,"claude-sonnet-4-6":1}`))
	require.NoError(t, setting.UpdateUserUsableGroupsByJSONString(`{"default":"Default","private-u-router":"Private","enterprise":"Enterprise"}`))
	service.InitHttpClient()
	require.NoError(t, model.InitDB())
	require.NoError(t, model.InitLogDB())

	user := &model.User{
		Username: "router-user",
		Password: "password123",
		Role:     common.RoleCommonUser,
		Status:   common.UserStatusEnabled,
		Group:    "private-u-router",
		Quota:    100000000,
	}
	require.NoError(t, model.DB.Create(user).Error)
	token := &model.Token{
		UserId:         user.Id,
		Key:            "routerflowkey",
		Status:         common.TokenStatusEnabled,
		Name:           "router-flow-token",
		ExpiredTime:    -1,
		RemainQuota:    100000000,
		UnlimitedQuota: true,
		Group:          "private-u-router",
	}
	require.NoError(t, model.DB.Create(token).Error)

	gin.SetMode(gin.TestMode)
	engine := gin.New()
	SetRelayRouter(engine)
	return engine
}

func seedRouterBoundChannel(
	t *testing.T,
	channelType int,
	name string,
	key string,
	baseURL string,
	modelName string,
) {
	t.Helper()

	autoBan := 0
	priority := int64(0)
	weight := uint(0)
	tag := "router-oauth"
	channel := &model.Channel{
		Type:     channelType,
		Key:      key,
		Status:   common.ChannelStatusEnabled,
		Name:     name,
		Weight:   &weight,
		BaseURL:  &baseURL,
		Models:   modelName,
		Group:    "private-u-router",
		Priority: &priority,
		AutoBan:  &autoBan,
		Tag:      &tag,
	}
	require.NoError(t, model.DB.Create(channel).Error)
	require.NoError(t, channel.AddAbilities(nil))
}

func TestRouterBoundCodexCredentialRelaysThroughNewAPIResponses(t *testing.T) {
	engine := setupRouterBoundRelayTest(t)
	captured := make(chan capturedRelayRequest, 1)
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		captured <- capturedRelayRequest{Path: r.URL.Path, Header: r.Header.Clone(), Body: string(body)}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{
			"id":"resp_router_codex",
			"object":"response",
			"created_at":1,
			"status":"completed",
			"model":"gpt-5.4",
			"output":[{"type":"message","id":"msg_1","status":"completed","role":"assistant","content":[{"type":"output_text","text":"OK","annotations":[]}]}],
			"usage":{"input_tokens":1,"output_tokens":1,"total_tokens":2}
		}`))
	}))
	defer upstream.Close()
	seedRouterBoundChannel(
		t,
		constant.ChannelTypeCodex,
		"router-codex-u-router",
		`{"access_token":"router-bound-access","refresh_token":"router-bound-refresh","account_id":"acct-router","type":"codex"}`,
		upstream.URL,
		"gpt-5.4",
	)

	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(
		http.MethodPost,
		"/v1/responses",
		strings.NewReader(`{"model":"gpt-5.4","input":[{"role":"user","content":"Reply with OK"}],"stream":false}`),
	)
	request.Header.Set("Authorization", "Bearer sk-routerflowkey")
	request.Header.Set("Content-Type", "application/json")

	engine.ServeHTTP(recorder, request)

	require.Equal(t, http.StatusOK, recorder.Code, recorder.Body.String())
	require.Contains(t, recorder.Body.String(), "resp_router_codex")
	got := <-captured
	require.Equal(t, "/backend-api/codex/responses", got.Path)
	require.Equal(t, "Bearer router-bound-access", got.Header.Get("Authorization"))
	require.Equal(t, "acct-router", got.Header.Get("chatgpt-account-id"))
	require.Equal(t, "responses=experimental", got.Header.Get("OpenAI-Beta"))
	require.Contains(t, got.Body, `"model":"gpt-5.4"`)
	require.Contains(t, got.Body, `"store":false`)
}

func TestRouterBoundClaudeCredentialRelaysThroughNewAPIBridgeChannel(t *testing.T) {
	engine := setupRouterBoundRelayTest(t)
	captured := make(chan capturedRelayRequest, 1)
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		captured <- capturedRelayRequest{Path: r.URL.Path, Header: r.Header.Clone(), Body: string(body)}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{
			"id":"msg_router_claude",
			"type":"message",
			"role":"assistant",
			"model":"claude-sonnet-4-6",
			"content":[{"type":"text","text":"OK"}],
			"usage":{"input_tokens":1,"output_tokens":1}
		}`))
	}))
	defer upstream.Close()
	seedRouterBoundChannel(
		t,
		constant.ChannelTypeAnthropic,
		"router-claude-max-u-router",
		"router-bridge-secret",
		upstream.URL+"/bridge/upstreams/credentials/cred-router/anthropic",
		"claude-sonnet-4-6",
	)

	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(
		http.MethodPost,
		"/v1/messages",
		strings.NewReader(`{"model":"claude-sonnet-4-6","max_tokens":64,"messages":[{"role":"user","content":"Reply with OK"}],"stream":false}`),
	)
	request.Header.Set("x-api-key", "sk-routerflowkey")
	request.Header.Set("Content-Type", "application/json")

	engine.ServeHTTP(recorder, request)

	require.Equal(t, http.StatusOK, recorder.Code, recorder.Body.String())
	require.Contains(t, recorder.Body.String(), "msg_router_claude")
	got := <-captured
	require.Equal(t, "/bridge/upstreams/credentials/cred-router/anthropic/v1/messages", got.Path)
	require.Equal(t, "router-bridge-secret", got.Header.Get("x-api-key"))
	require.Equal(t, "2023-06-01", got.Header.Get("anthropic-version"))
	require.Contains(t, got.Body, `"model":"claude-sonnet-4-6"`)
}
