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
      // 新建行程改为当前页弹窗：深链落到首页并由 AppShell 唤起 CreateTripDialog
      redirect: (to) => ({
        name: 'home',
        query: {
        ...(typeof to.query.city === 'string' ? { city: to.query.city } : {}),
        ...(to.query.new === '1' ? { new: '1' } : {}),
      },
      }),
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
      // 详情页三栏工作台需要全宽容器（v2.6 §19.3）：AppShell 的 content-inner 按 meta.wide 放开 max-width
      // immersive（v2.7 §20 R1）：整页不滚的视口固定布局——content 去内边距、页脚让位
      meta: { wide: true, immersive: true },
    },
    {
      path: '/atlas',
      name: 'atlas',
      component: () => import('../views/AtlasView.vue'),
    },
    {
      path: '/templates',
      name: 'templates',
      component: () => import('../views/TemplateSquareView.vue'),
    },
    {
      path: '/s/:token',
      name: 'share',
      component: () => import('../views/ShareView.vue'),
      // 公开只读页（SPEC §1.3）：守卫跳过登录判定、AppShell 不渲染（ShareView 自带轻顶栏）
      meta: { public: true },
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

router.beforeEach(async (to) => {
  // 公开页（分享 /s/:token）跳过登录判定：分享链接必须匿名可开（SPEC §1.3）
  if (to.meta.public === true) return true
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
  // 管理端：localStorage.role 只是展示缓存，不能作为唯一授权依据（R5-2）——
  // 服务端回查 GET /api/user/info 的角色为准（后端 user_router 挂了默认拒绝依赖）。
  // 延迟 import 打破 router → api/auth → api/request → router 的静态环。
  if (to.meta.requiresAdmin) {
    try {
      const { getUserInfo } = await import('../api/auth')
      const res = await getUserInfo({ skipErrorMessage: true })
      if (res.data?.role === 'admin') {
        localStorage.setItem('role', 'admin')
        return true
      }
      localStorage.removeItem('role')
      return { name: 'home' }
    } catch {
      // 未登录/无权限/网络失败一律不放行：401 时 request 层已带跳登录，这里只兜底回首页
      localStorage.removeItem('role')
      return { name: 'home' }
    }
  }
  return true
})

export default router