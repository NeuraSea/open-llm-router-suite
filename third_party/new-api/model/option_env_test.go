package model

import (
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/setting/system_setting"
)

func withServerAddressState(t *testing.T, optionValue string, runtimeValue string) {
	t.Helper()

	common.OptionMapRWMutex.Lock()
	oldOptionMap := common.OptionMap
	oldRuntime := system_setting.ServerAddress
	common.OptionMap = map[string]string{"ServerAddress": optionValue}
	system_setting.ServerAddress = runtimeValue
	common.OptionMapRWMutex.Unlock()

	t.Cleanup(func() {
		common.OptionMapRWMutex.Lock()
		common.OptionMap = oldOptionMap
		system_setting.ServerAddress = oldRuntime
		common.OptionMapRWMutex.Unlock()
	})
}

func currentServerAddressOption() string {
	common.OptionMapRWMutex.RLock()
	defer common.OptionMapRWMutex.RUnlock()
	return common.OptionMap["ServerAddress"]
}

func TestApplyServerAddressFromEnvSetsDeploymentDefault(t *testing.T) {
	withServerAddressState(t, "", "http://localhost:3000")
	t.Setenv("SERVER_ADDRESS", "https://api-new.singularity-x.ai/")

	applyServerAddressFromEnv()

	if currentServerAddressOption() != "https://api-new.singularity-x.ai" {
		t.Fatalf("unexpected ServerAddress option: %q", currentServerAddressOption())
	}
	if system_setting.ServerAddress != "https://api-new.singularity-x.ai" {
		t.Fatalf("unexpected runtime ServerAddress: %q", system_setting.ServerAddress)
	}
}

func TestApplyServerAddressFromEnvKeepsAdminConfiguredAddress(t *testing.T) {
	withServerAddressState(
		t,
		"https://admin-configured.example",
		"https://admin-configured.example",
	)
	t.Setenv("SERVER_ADDRESS", "https://api-new.singularity-x.ai")

	applyServerAddressFromEnv()

	if currentServerAddressOption() != "https://admin-configured.example" {
		t.Fatalf("ServerAddress option was overwritten: %q", currentServerAddressOption())
	}
	if system_setting.ServerAddress != "https://admin-configured.example" {
		t.Fatalf("runtime ServerAddress was overwritten: %q", system_setting.ServerAddress)
	}
}
