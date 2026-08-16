<template>
  <div class="login-page">
    <!-- 渐变背景装饰 -->
    <div class="bg-decoration">
      <div class="bg-blob blob-1"></div>
      <div class="bg-blob blob-2"></div>
      <div class="bg-blob blob-3"></div>
      <div class="bg-grid"></div>
    </div>

    <div class="login-container">
      <!-- 左侧品牌区 -->
      <div class="brand-section">
        <div class="brand-logo">
          <el-icon :size="48"><DataAnalysis /></el-icon>
        </div>
        <h1 class="brand-title">Data Insight</h1>
        <p class="brand-subtitle">数据洞察平台</p>
        <div class="brand-desc">
          <p>从数据清洗、特征工程到机器学习与 AI 智能分析</p>
          <p>一站式完成数据洞察的全流程</p>
        </div>
      </div>

      <!-- 右侧表单区 -->
      <div class="form-section">
        <div class="form-card">
          <h2 class="form-title">{{ activeTab === 'login' ? '欢迎回来' : '创建账号' }}</h2>
          <p class="form-subtitle">{{ activeTab === 'login' ? '登录以继续使用平台' : '注册一个新账号开始使用' }}</p>

          <!-- Tab 切换 -->
          <el-tabs v-model="activeTab" class="login-tabs" @tab-change="handleTabChange">
            <el-tab-pane label="登录" name="login" />
            <el-tab-pane label="注册" name="register" />
          </el-tabs>

          <!-- 登录表单 -->
          <el-form
            v-if="activeTab === 'login'"
            ref="loginFormRef"
            :model="loginForm"
            :rules="loginRules"
            class="login-form"
            @keyup.enter="handleLogin"
          >
            <el-form-item prop="username">
              <el-input
                v-model="loginForm.username"
                placeholder="请输入用户名"
                size="large"
                :prefix-icon="User"
              />
            </el-form-item>
            <el-form-item prop="password">
              <el-input
                v-model="loginForm.password"
                type="password"
                placeholder="请输入密码"
                size="large"
                :prefix-icon="Lock"
                show-password
              />
            </el-form-item>
            <el-button
              type="primary"
              size="large"
              class="submit-btn"
              :loading="loginLoading"
              @click="handleLogin"
            >
              登 录
            </el-button>
            <div class="form-links">
              <span class="link-muted">忘记密码？</span>
              <router-link to="/contact-admin" class="link-admin">联系管理员 →</router-link>
            </div>
          </el-form>

          <!-- 注册表单 -->
          <el-form
            v-else
            ref="registerFormRef"
            :model="registerForm"
            :rules="registerRules"
            class="login-form"
            @keyup.enter="handleRegister"
          >
            <el-form-item prop="username">
              <el-input
                v-model="registerForm.username"
                placeholder="请输入用户名"
                size="large"
                :prefix-icon="User"
              />
            </el-form-item>
            <el-form-item prop="password">
              <el-input
                v-model="registerForm.password"
                type="password"
                placeholder="请输入密码"
                size="large"
                :prefix-icon="Lock"
                show-password
              />
            </el-form-item>
            <el-form-item prop="confirmPassword">
              <el-input
                v-model="registerForm.confirmPassword"
                type="password"
                placeholder="请确认密码"
                size="large"
                :prefix-icon="Lock"
                show-password
              />
            </el-form-item>
            <el-button
              type="primary"
              size="large"
              class="submit-btn"
              :loading="registerLoading"
              @click="handleRegister"
            >
              注 册
            </el-button>
          </el-form>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { DataAnalysis, User, Lock } from '@element-plus/icons-vue'
import { login, register, setAuth, isLoggedIn, getCurrentUser, updateUserInfo } from '../api/index.js'

const route = useRoute()
const router = useRouter()

const activeTab = ref('login')
const loginLoading = ref(false)
const registerLoading = ref(false)
const loginFormRef = ref(null)
const registerFormRef = ref(null)

const loginForm = reactive({
  username: '',
  password: ''
})

const registerForm = reactive({
  username: '',
  password: '',
  confirmPassword: ''
})

// 登录表单验证规则
const loginRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, max: 20, message: '用户名长度为 2-20 个字符', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 32, message: '密码长度为 6-32 个字符', trigger: 'blur' }
  ]
}

// 注册表单验证规则
const registerRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, max: 20, message: '用户名长度为 2-20 个字符', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 32, message: '密码长度为 6-32 个字符', trigger: 'blur' }
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    {
      validator: (rule, value, callback) => {
        if (value !== registerForm.password) {
          callback(new Error('两次输入的密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur'
    }
  ]
}

// 已登录直接跳转首页
onMounted(() => {
  if (isLoggedIn()) {
    router.push('/')
  }
})

// Tab 切换
function handleTabChange() {
  loginFormRef.value?.clearValidate()
  registerFormRef.value?.clearValidate()
}

// 登录
async function handleLogin() {
  if (!loginFormRef.value) return
  const valid = await loginFormRef.value.validate().catch(() => false)
  if (!valid) return

  loginLoading.value = true
  try {
    const res = await login(loginForm.username, loginForm.password)
    setAuth(res.data.access_token, { username: loginForm.username })
    
    // 获取完整用户信息
    try {
      const userRes = await getCurrentUser()
      updateUserInfo(userRes.data)
    } catch {
      // 获取用户信息失败不影响登录
    }
    
    ElMessage.success('登录成功')
    
    // 跳转到 redirect 参数指定的页面，或默认跳转到首页
    const redirect = route.query.redirect || '/'
    router.push(redirect)
  } catch (err) {
    // 后端统一错误格式：具体错误在 message/error 字段，detail 为 null
    ElMessage.error(err.response?.data?.message || err.response?.data?.error || err.response?.data?.detail || '登录失败，请检查用户名和密码')
  } finally {
    loginLoading.value = false
  }
}

// 注册
async function handleRegister() {
  if (!registerFormRef.value) return
  const valid = await registerFormRef.value.validate().catch(() => false)
  if (!valid) return

  registerLoading.value = true
  try {
    await register(registerForm.username, registerForm.password)
    ElMessage.success('注册成功，请登录')
    activeTab.value = 'login'
    loginForm.username = registerForm.username
    loginForm.password = registerForm.password
  } catch (err) {
    ElMessage.error(err.response?.data?.message || err.response?.data?.error || err.response?.data?.detail || '注册失败，请稍后重试')
  } finally {
    registerLoading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
}

/* 背景装饰 */
.bg-decoration {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

.bg-blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.4;
}

.blob-1 {
  width: 400px;
  height: 400px;
  background: #3b82f6;
  top: -100px;
  left: -100px;
  animation: float 20s ease-in-out infinite;
}

.blob-2 {
  width: 300px;
  height: 300px;
  background: #8b5cf6;
  bottom: -50px;
  right: -50px;
  animation: float 25s ease-in-out infinite reverse;
}

.blob-3 {
  width: 250px;
  height: 250px;
  background: #06b6d4;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  animation: float 15s ease-in-out infinite;
}

@keyframes float {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(30px, -30px) scale(1.05); }
  66% { transform: translate(-20px, 20px) scale(0.95); }
}

.bg-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
  background-size: 40px 40px;
}

/* 主容器 */
.login-container {
  width: 100%;
  max-width: 900px;
  display: flex;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
  position: relative;
  z-index: 1;
  margin: 20px;
}

/* 左侧品牌区 */
.brand-section {
  flex: 1;
  background: linear-gradient(135deg, #1e40af 0%, #7c3aed 100%);
  padding: 60px 40px;
  color: white;
  display: flex;
  flex-direction: column;
  justify-content: center;
  position: relative;
  overflow: hidden;
}

.brand-section::before {
  content: '';
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at 20% 80%, rgba(59, 130, 246, 0.3) 0%, transparent 50%),
    radial-gradient(circle at 80% 20%, rgba(139, 92, 246, 0.3) 0%, transparent 50%);
}

.brand-logo {
  width: 80px;
  height: 80px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.15);
  backdrop-filter: blur(10px);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 24px;
  position: relative;
  z-index: 1;
}

.brand-title {
  font-size: 32px;
  font-weight: 700;
  margin: 0 0 8px 0;
  position: relative;
  z-index: 1;
}

.brand-subtitle {
  font-size: 16px;
  opacity: 0.8;
  margin: 0 0 32px 0;
  position: relative;
  z-index: 1;
}

.brand-desc {
  font-size: 14px;
  opacity: 0.7;
  line-height: 1.8;
  position: relative;
  z-index: 1;
}

.brand-desc p {
  margin: 4px 0;
}

/* 右侧表单区 */
.form-section {
  flex: 1;
  background: white;
  padding: 48px 40px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.form-card {
  width: 100%;
}

.form-title {
  font-size: 24px;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 8px 0;
}

.form-subtitle {
  font-size: 14px;
  color: #64748b;
  margin: 0 0 24px 0;
}

.login-tabs {
  margin-bottom: 24px;
}

.login-tabs :deep(.el-tabs__nav-wrap::after) {
  background-color: #e2e8f0;
}

.login-form {
  margin-top: 16px;
}

.submit-btn {
  width: 100%;
  margin-top: 8px;
  font-weight: 500;
  letter-spacing: 4px;
}

.form-links {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 14px;
  font-size: 13px;
}
.link-muted {
  color: #94a3b8;
}
.link-admin {
  color: #3b82f6;
  font-weight: 500;
  text-decoration: none;
}
.link-admin:hover {
  text-decoration: underline;
}

/* 响应式 */
@media (max-width: 768px) {
  .login-container {
    flex-direction: column;
    max-width: 400px;
  }

  .brand-section {
    padding: 40px 32px;
    text-align: center;
    align-items: center;
  }

  .brand-desc {
    display: none;
  }

  .form-section {
    padding: 32px 28px;
  }
}
</style>
