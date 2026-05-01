package service

import (
	"os"
	"strings"

	"github.com/QuantumNous/new-api/setting"
	"github.com/QuantumNous/new-api/setting/ratio_setting"
)

func GetUserUsableGroups(userGroup string) map[string]string {
	groupsCopy := setting.GetUserUsableGroupsCopy()
	if userGroup != "" {
		specialSettings, b := ratio_setting.GetGroupRatioSetting().GroupSpecialUsableGroup.Get(userGroup)
		if b {
			// 处理特殊可用分组
			for specialGroup, desc := range specialSettings {
				if strings.HasPrefix(specialGroup, "-:") {
					// 移除分组
					groupToRemove := strings.TrimPrefix(specialGroup, "-:")
					delete(groupsCopy, groupToRemove)
				} else if strings.HasPrefix(specialGroup, "+:") {
					// 添加分组
					groupToAdd := strings.TrimPrefix(specialGroup, "+:")
					groupsCopy[groupToAdd] = desc
				} else {
					// 直接添加分组
					groupsCopy[specialGroup] = desc
				}
			}
		}
		// 如果userGroup不在UserUsableGroups中，返回UserUsableGroups + userGroup
		if _, ok := groupsCopy[userGroup]; !ok {
			groupsCopy[userGroup] = "用户分组"
		}
		if routerSSOEnabled() && strings.HasPrefix(userGroup, "private-") {
			if _, ok := groupsCopy["auto"]; !ok {
				groupsCopy["auto"] = "自动选择分组"
			}
			enterpriseGroup := strings.TrimSpace(os.Getenv("ROUTER_SSO_ENTERPRISE_GROUP"))
			if enterpriseGroup != "" {
				if _, ok := groupsCopy[enterpriseGroup]; !ok {
					groupsCopy[enterpriseGroup] = "企业共享分组"
				}
			}
		}
	}
	return groupsCopy
}

func GroupInUserUsableGroups(userGroup, groupName string) bool {
	_, ok := GetUserUsableGroups(userGroup)[groupName]
	return ok
}

// GetUserAutoGroup 根据用户分组获取自动分组设置
func GetUserAutoGroup(userGroup string) []string {
	groups := GetUserUsableGroups(userGroup)
	autoGroups := make([]string, 0)
	seen := make(map[string]bool)
	appendGroup := func(group string) {
		if group == "" || seen[group] {
			return
		}
		if _, ok := groups[group]; ok {
			autoGroups = append(autoGroups, group)
			seen[group] = true
		}
	}
	if routerSSOEnabled() && strings.HasPrefix(userGroup, "private-") {
		appendGroup(userGroup)
		appendGroup(strings.TrimSpace(os.Getenv("ROUTER_SSO_ENTERPRISE_GROUP")))
	}
	for _, group := range setting.GetAutoGroups() {
		appendGroup(group)
	}
	return autoGroups
}

func routerSSOEnabled() bool {
	value := strings.ToLower(strings.TrimSpace(os.Getenv("ROUTER_SSO_ENABLED")))
	return value == "1" || value == "true" || value == "yes" || value == "on"
}

// GetUserGroupRatio 获取用户使用某个分组的倍率
// userGroup 用户分组
// group 需要获取倍率的分组
func GetUserGroupRatio(userGroup, group string) float64 {
	ratio, ok := ratio_setting.GetGroupGroupRatio(userGroup, group)
	if ok {
		return ratio
	}
	return ratio_setting.GetGroupRatio(group)
}
