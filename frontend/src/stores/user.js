import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { login as loginApi, register as registerApi } from '../api/auth'
import router from '../router'

export const useUserStore = defineStore('user', () => {
  const token = ref(localStorage.getItem('token') || '')
  const user = ref(JSON.parse(localStorage.getItem('user') || 'null'))

  const isLoggedIn = computed(() => !!token.value)

  // Phase 5：管理员判定（服务端以 is_admin 字段 / ADMIN_USERNAMES 白名单为准，此处仅控制前端展示）
  const isAdmin = computed(() => !!(user.value && user.value.is_admin))

  async function login(username, password) {
    const res = await loginApi({ username, password })
    token.value = res.access_token
    user.value = res.user
    localStorage.setItem('token', res.access_token)
    localStorage.setItem('user', JSON.stringify(res.user))
    return res
  }

  async function register(username, password) {
    await registerApi({ username, password })
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    router.push('/login')
  }

  return { token, user, isLoggedIn, isAdmin, login, register, logout }
})
