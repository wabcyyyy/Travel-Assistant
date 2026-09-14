import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
    },
    {
      path: '/',
      name: 'home',
      component: () => import('../views/HomeView.vue'),
    },
    {
      path: '/generate',
      name: 'generate',
      component: () => import('../views/GenerateView.vue'),
    },
    {
      path: '/trips',
      name: 'trips',
      component: () => import('../views/TripsView.vue'),
    },
    {
      path: '/trips/:id',
      name: 'trip-detail',
      component: () => import('../views/TripDetailView.vue'),
    },
    {
      path: '/admin',
      component: () => import('../views/admin/AdminLayout.vue'),
      meta: { requiresAdmin: true },
      children: [
        {
          path: '',
          name: 'admin-dashboard',
          component: () => import('../views/admin/AdminDashboard.vue'),
        },
        {
          path: 'users',
          name: 'admin-users',
          component: () => import('../views/admin/AdminUsersView.vue'),
        },
        {
          path: 'itineraries',
          name: 'admin-itineraries',
          component: () => import('../views/admin/AdminItinerariesView.vue'),
        },
        {
          path: 'tokens',
          name: 'admin-tokens',
          component: () => import('../views/admin/AdminTokensView.vue'),
        },
        {
          path: 'agent',
          name: 'admin-agent',
          component: () => import('../views/admin/AdminAgentView.vue'),
        },
      ],
    },
  ],
})

router.beforeEach((to) => {
  // 凭据在 HttpOnly Cookie；本地仅保存展示用 username/role
  const authed = Boolean(localStorage.getItem('username'))
  if (!authed && to.name !== 'login') {
    // 携带原目标：登录/注册成功后回跳（分享链接 /trips/58 → 登录 → 回到该行程）
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (authed && to.name === 'login') {
    const redirect = to.query.redirect
    if (typeof redirect === 'string' && redirect.startsWith('/')) {
      return redirect
    }
    return { name: 'home' }
  }
  if (to.meta.requiresAdmin && localStorage.getItem('role') !== 'admin') {
    return { name: 'home' }
  }
})

export default router