import { createRouter, createWebHistory } from 'vue-router'
import { getRoleFromToken, getActiveToken, getActiveRole } from '@/stores/auth'

const routes = [
  {
    path: '/',
    redirect: '/login',
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { guest: true },
  },
  // ===== 学生端 =====
  {
    path: '/student',
    component: () => import('@/views/student/StudentLayout.vue'),
    meta: { requiresAuth: true, role: 'student' },
    redirect: '/student/home',
    children: [
      {
        path: 'home',
        name: 'StudentHome',
        component: () => import('@/views/student/AgentView.vue'),
      },
      {
        path: 'history',
        name: 'StudentHistory',
        component: () => import('@/views/student/HistoryView.vue'),
      },
      {
        path: 'photo-search',
        name: 'StudentPhotoSearch',
        component: () => import('@/views/student/PhotoSearchView.vue'),
      },
      {
        path: 'wrong-book',
        name: 'StudentWrongBook',
        component: () => import('@/views/student/WrongBookView.vue'),
      },
      {
        path: 'conversations',
        name: 'StudentConversations',
        component: () => import('@/views/student/ConversationHistory.vue'),
      },
      {
        path: 'knowledge-graph',
        name: 'StudentKnowledgeGraph',
        component: () => import('@/views/student/KnowledgeGraphView.vue'),
      },
    ],
  },
  // ===== 管理端 =====
  {
    path: '/admin',
    component: () => import('@/views/admin/AdminLayout.vue'),
    meta: { requiresAuth: true, role: 'admin' },
    redirect: '/admin/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'AdminDashboard',
        component: () => import('@/views/admin/DashboardView.vue'),
      },
      {
        path: 'upload',
        name: 'AdminUpload',
        component: () => import('@/views/admin/UploadView.vue'),
      },
      {
        path: 'evaluate',
        name: 'AdminEvaluate',
        component: () => import('@/views/admin/EvaluateView.vue'),
      },
      {
        path: 'ragas',
        redirect: '/admin/evaluate',
      },
      {
        path: 'eval-history',
        name: 'AdminEvalHistory',
        component: () => import('@/views/admin/EvalHistory.vue'),
      },
      {
        path: 'knowledge',
        name: 'AdminKnowledge',
        component: () => import('@/views/admin/KnowledgeView.vue'),
      },
      {
        path: 'traces',
        redirect: '/admin/visualize',
      },
      {
        path: 'visualize',
        name: 'AdminVisualize',
        component: () => import('@/views/admin/VisualizeView.vue'),
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/NotFound.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// ======================== 路由守卫 ========================
router.beforeEach((to, from, next) => {
  // 🔑 关键修复：传入 to.path 确保导航过渡期间读取正确的 token
  const activeRoleForDest = getActiveRole(to.path)
  const token = getActiveToken(activeRoleForDest)

  if (to.meta.requiresAuth) {
    if (!token) {
      return next('/login')
    }

    const jwtRole = getRoleFromToken(token)
    if (!jwtRole) {
      // token 无效或过期 → 清空目标角色存储
      if (activeRoleForDest) {
        localStorage.removeItem(`edurag_token_${activeRoleForDest}`)
        localStorage.removeItem(`edurag_user_${activeRoleForDest}`)
      }
      return next('/login')
    }

    if (to.meta.role && jwtRole !== to.meta.role) {
      // 角色不匹配 → 重定向到正确端
      return next(jwtRole === 'admin' ? '/admin/dashboard' : '/student/home')
    }
  }

  if (to.meta.guest && token) {
    const jwtRole = getRoleFromToken(token)
    if (jwtRole) {
      return next(jwtRole === 'admin' ? '/admin/dashboard' : '/student/home')
    }
    // token 过期 → 清理
    if (activeRoleForDest) {
      localStorage.removeItem(`edurag_token_${activeRoleForDest}`)
      localStorage.removeItem(`edurag_user_${activeRoleForDest}`)
    }
  }

  next()
})

export default router