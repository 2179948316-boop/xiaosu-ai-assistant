import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue'),
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('../views/Register.vue'),
  },
  {
    path: '/',
    name: 'Chat',
    component: () => import('../views/Chat.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/documents',
    name: 'Documents',
    component: () => import('../views/Documents.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/admin/logs',
    name: 'AdminLogs',
    component: () => import('../views/AdminLogs.vue'),
    meta: { requiresAuth: true, requiresAdmin: true },
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('../views/Settings.vue'),
    meta: { requiresAuth: true, requiresAdmin: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  if (to.meta.requiresAuth && !token) {
    next('/login')
  } else if ((to.path === '/login' || to.path === '/register') && token) {
    next('/')
  } else if (to.meta.requiresAdmin) {
    // Phase 5：管理后台路由仅管理员可见（服务端接口仍有 403 兜底）
    const user = JSON.parse(localStorage.getItem('user') || 'null')
    if (!user || !user.is_admin) {
      next('/')
    } else {
      next()
    }
  } else {
    next()
  }
})

export default router
