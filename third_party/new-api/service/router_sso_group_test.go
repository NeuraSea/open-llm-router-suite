package service

import (
	"reflect"
	"testing"

	"github.com/QuantumNous/new-api/setting"
)

func TestRouterSSOAutoGroupPrefersPrivateThenEnterpriseGroup(t *testing.T) {
	t.Setenv("ROUTER_SSO_ENABLED", "true")
	t.Setenv("ROUTER_SSO_ENTERPRISE_GROUP", "enterprise")
	if err := setting.UpdateAutoGroupsByJsonString(`["default"]`); err != nil {
		t.Fatalf("set auto groups: %v", err)
	}
	t.Cleanup(func() {
		_ = setting.UpdateAutoGroupsByJsonString(`["default"]`)
	})

	got := GetUserAutoGroup("private-42")
	want := []string{"private-42", "enterprise", "default"}

	if !reflect.DeepEqual(got, want) {
		t.Fatalf("auto groups: got %#v, want %#v", got, want)
	}
}

func TestRouterSSOPrivateUserCanUseAutoGroup(t *testing.T) {
	t.Setenv("ROUTER_SSO_ENABLED", "true")

	if !GroupInUserUsableGroups("private-42", "auto") {
		t.Fatal("expected Router SSO private user to be allowed to use auto group")
	}
}
