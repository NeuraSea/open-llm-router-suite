package middleware

import (
	"crypto/rsa"
	"crypto/sha256"
	"crypto/subtle"
	"crypto/x509"
	"encoding/hex"
	"encoding/pem"
	"fmt"
	"net/http"
	"os"
	"strings"
	"unicode"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/model"

	"github.com/gin-contrib/sessions"
	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"
)

const routerSSOAssertionHeader = "X-Router-SSO-Assertion"

func RouterSSO() gin.HandlerFunc {
	return func(c *gin.Context) {
		if !routerSSOEnabled() {
			c.Next()
			return
		}

		assertion := strings.TrimSpace(c.Request.Header.Get(routerSSOAssertionHeader))
		if assertion == "" {
			setNewAPIUserHeaderFromSession(c)
			c.Next()
			return
		}

		claims, err := verifyRouterSSOAssertion(assertion)
		if err != nil {
			c.JSON(http.StatusUnauthorized, gin.H{
				"success": false,
				"message": "invalid Router SSO assertion",
			})
			c.Abort()
			return
		}

		user, err := upsertRouterSSOUser(claims)
		if err != nil {
			common.SysLog("router sso user sync failed: " + err.Error())
			c.JSON(http.StatusInternalServerError, gin.H{
				"success": false,
				"message": "failed to sync Router SSO user",
			})
			c.Abort()
			return
		}
		if user.Status == common.UserStatusDisabled {
			c.JSON(http.StatusForbidden, gin.H{
				"success": false,
				"message": "user is disabled",
			})
			c.Abort()
			return
		}

		writeRouterSSOSession(c, user)
		c.Next()
	}
}

type routerSSOClaims struct {
	Sub     string
	Email   string
	Name    string
	Role    string
	Picture string
}

func routerSSOEnabled() bool {
	value := strings.ToLower(strings.TrimSpace(os.Getenv("ROUTER_SSO_ENABLED")))
	return value == "1" || value == "true" || value == "yes" || value == "on"
}

func verifyRouterSSOAssertion(assertion string) (*routerSSOClaims, error) {
	publicKey, err := routerSSOPublicKey()
	if err != nil {
		return nil, err
	}
	issuer := strings.TrimSpace(os.Getenv("ROUTER_SSO_ISSUER"))
	audience := strings.TrimSpace(os.Getenv("ROUTER_SSO_AUDIENCE"))
	if audience == "" {
		audience = "new-api"
	}
	claims := jwt.MapClaims{}
	options := []jwt.ParserOption{
		jwt.WithAudience(audience),
		jwt.WithExpirationRequired(),
	}
	if issuer != "" {
		options = append(options, jwt.WithIssuer(issuer))
	}
	token, err := jwt.ParseWithClaims(assertion, claims, func(token *jwt.Token) (interface{}, error) {
		if token.Method.Alg() != jwt.SigningMethodRS256.Alg() {
			return nil, fmt.Errorf("unexpected signing method: %s", token.Method.Alg())
		}
		return publicKey, nil
	}, options...)
	if err != nil {
		return nil, err
	}
	if token == nil || !token.Valid {
		return nil, fmt.Errorf("invalid token")
	}
	sub, _ := claims["sub"].(string)
	if strings.TrimSpace(sub) == "" {
		return nil, fmt.Errorf("missing subject")
	}
	email, _ := claims["email"].(string)
	name, _ := claims["name"].(string)
	role, _ := claims["role"].(string)
	picture, _ := claims["picture"].(string)
	if strings.TrimSpace(picture) == "" {
		picture, _ = claims["avatar_url"].(string)
	}
	return &routerSSOClaims{
		Sub:     strings.TrimSpace(sub),
		Email:   trimMax(email, 50),
		Name:    trimMax(name, 20),
		Role:    strings.ToLower(strings.TrimSpace(role)),
		Picture: trimMax(picture, 512),
	}, nil
}

func routerSSOPublicKey() (*rsa.PublicKey, error) {
	pemValue := strings.TrimSpace(os.Getenv("ROUTER_SSO_PUBLIC_KEY_PEM"))
	if pemValue == "" {
		return nil, fmt.Errorf("ROUTER_SSO_PUBLIC_KEY_PEM is required")
	}
	pemValue = strings.ReplaceAll(pemValue, "\\n", "\n")
	block, _ := pem.Decode([]byte(pemValue))
	if block == nil {
		return nil, fmt.Errorf("invalid public key pem")
	}
	if key, err := x509.ParsePKIXPublicKey(block.Bytes); err == nil {
		if rsaKey, ok := key.(*rsa.PublicKey); ok {
			return rsaKey, nil
		}
	}
	if key, err := x509.ParsePKCS1PublicKey(block.Bytes); err == nil {
		return key, nil
	}
	if cert, err := x509.ParseCertificate(block.Bytes); err == nil {
		if rsaKey, ok := cert.PublicKey.(*rsa.PublicKey); ok {
			return rsaKey, nil
		}
	}
	return nil, fmt.Errorf("ROUTER_SSO_PUBLIC_KEY_PEM must contain an RSA public key")
}

func upsertRouterSSOUser(claims *routerSSOClaims) (*model.User, error) {
	user := model.User{OidcId: claims.Sub}
	if model.IsOidcIdAlreadyTaken(claims.Sub) {
		if err := user.FillUserByOidcId(); err != nil {
			return nil, err
		}
		return updateRouterSSOUser(&user, claims)
	}

	user = model.User{
		Username:    routerSSOUsername(claims.Sub),
		DisplayName: routerSSODisplayName(claims),
		Email:       claims.Email,
		OidcId:      claims.Sub,
		Role:        routerSSORole(claims.Role),
		Status:      common.UserStatusEnabled,
		Group:       routerSSOPrivateGroup(claims.Sub),
	}
	setRouterSSOAvatar(&user, claims.Picture)
	if err := user.Insert(0); err != nil {
		return nil, err
	}
	return &user, nil
}

func updateRouterSSOUser(user *model.User, claims *routerSSOClaims) (*model.User, error) {
	updates := map[string]interface{}{
		"role": routerSSORole(claims.Role),
	}
	if claims.Email != "" && !constantTimeStringEqual(user.Email, claims.Email) {
		updates["email"] = claims.Email
	}
	displayName := routerSSODisplayName(claims)
	if displayName != "" && !constantTimeStringEqual(user.DisplayName, displayName) {
		updates["display_name"] = displayName
	}
	desiredGroup := routerSSOPrivateGroup(claims.Sub)
	if user.Group == "" || user.Group == "default" || strings.HasPrefix(user.Group, "private-") {
		if !constantTimeStringEqual(user.Group, desiredGroup) {
			updates["group"] = desiredGroup
		}
	}
	if setting, ok := routerSSOAvatarSetting(user, claims.Picture); ok {
		updates["setting"] = setting
	}
	if err := model.DB.Model(&model.User{}).Where("id = ?", user.Id).Updates(updates).Error; err != nil {
		return nil, err
	}
	_ = model.InvalidateUserCache(user.Id)
	if err := user.FillUserById(); err != nil {
		return nil, err
	}
	return user, nil
}

func writeRouterSSOSession(c *gin.Context, user *model.User) {
	session := sessions.Default(c)
	session.Set("id", user.Id)
	session.Set("username", user.Username)
	session.Set("role", user.Role)
	session.Set("status", user.Status)
	session.Set("group", user.Group)
	_ = session.Save()

	c.Request.Header.Set("New-Api-User", fmt.Sprintf("%d", user.Id))
	c.Set("id", user.Id)
	c.Set("username", user.Username)
	c.Set("role", user.Role)
	c.Set("status", user.Status)
	c.Set("group", user.Group)
	c.Set("user_group", user.Group)
}

func setNewAPIUserHeaderFromSession(c *gin.Context) {
	if c.Request.Header.Get("New-Api-User") != "" {
		return
	}
	session := sessions.Default(c)
	id := session.Get("id")
	if id == nil {
		return
	}
	c.Request.Header.Set("New-Api-User", fmt.Sprintf("%v", id))
}

func routerSSORole(role string) int {
	switch role {
	case "root":
		return common.RoleRootUser
	case "admin":
		return common.RoleAdminUser
	default:
		return common.RoleCommonUser
	}
}

func routerSSOUsername(sub string) string {
	sum := sha256.Sum256([]byte(sub))
	return "sso_" + hex.EncodeToString(sum[:])[:16]
}

func routerSSODisplayName(claims *routerSSOClaims) string {
	if strings.TrimSpace(claims.Name) != "" {
		return trimMax(claims.Name, 20)
	}
	if strings.TrimSpace(claims.Email) != "" {
		return trimMax(strings.Split(claims.Email, "@")[0], 20)
	}
	return trimMax(claims.Sub, 20)
}

func routerSSOPrivateGroup(sub string) string {
	return "private-" + safeRouterSSOGroupFragment(sub)
}

func safeRouterSSOGroupFragment(value string) string {
	value = strings.TrimSpace(value)
	var builder strings.Builder
	lastDash := false
	for _, r := range value {
		if unicode.IsLetter(r) || unicode.IsDigit(r) || r == '_' || r == '-' {
			builder.WriteRune(r)
			lastDash = false
			continue
		}
		if !lastDash {
			builder.WriteRune('-')
			lastDash = true
		}
	}
	normalized := strings.Trim(builder.String(), "-")
	if normalized == "" {
		return "user"
	}
	runes := []rune(normalized)
	if len(runes) > 48 {
		return string(runes[:48])
	}
	return normalized
}

func setRouterSSOAvatar(user *model.User, avatarURL string) {
	if strings.TrimSpace(avatarURL) == "" {
		return
	}
	setting := user.GetSetting()
	setting.AvatarURL = strings.TrimSpace(avatarURL)
	user.SetSetting(setting)
}

func routerSSOAvatarSetting(user *model.User, avatarURL string) (string, bool) {
	avatarURL = strings.TrimSpace(avatarURL)
	if avatarURL == "" {
		return "", false
	}
	setting := user.GetSetting()
	if constantTimeStringEqual(setting.AvatarURL, avatarURL) {
		return "", false
	}
	setting.AvatarURL = avatarURL
	user.SetSetting(setting)
	return user.Setting, true
}

func trimMax(value string, maxLen int) string {
	value = strings.TrimSpace(value)
	runes := []rune(value)
	if len(runes) <= maxLen {
		return value
	}
	return string(runes[:maxLen])
}

func constantTimeStringEqual(a string, b string) bool {
	if len(a) != len(b) {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(a), []byte(b)) == 1
}
