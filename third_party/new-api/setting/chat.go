package setting

import (
	"encoding/json"
	"os"

	"github.com/QuantumNous/new-api/common"
)

var Chats = defaultChats()

func defaultChats() []map[string]string {
	libreChatURL := os.Getenv("LIBRECHAT_PUBLIC_URL")
	if libreChatURL == "" {
		libreChatURL = "/chat/"
	}
	return []map[string]string{
		{
			"LibreChat": libreChatURL,
		},
	}
}

func UpdateChatsByJsonString(jsonString string) error {
	Chats = make([]map[string]string, 0)
	return json.Unmarshal([]byte(jsonString), &Chats)
}

func Chats2JsonString() string {
	jsonBytes, err := json.Marshal(Chats)
	if err != nil {
		common.SysLog("error marshalling chats: " + err.Error())
		return "[]"
	}
	return string(jsonBytes)
}
