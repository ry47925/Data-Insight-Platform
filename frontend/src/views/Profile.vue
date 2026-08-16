<template>
  <div class="profile-page">
    <div class="page-head">
      <h2 class="page-title">个人中心</h2>
      <span class="page-sub">管理您的账号信息与安全设置</span>
    </div>

    <div class="profile-layout">
      <!-- 左侧信息卡 -->
      <div class="info-card">
        <div class="avatar-box">{{ avatarChar }}</div>
        <div class="user-name">{{ userInfo.username || '用户' }}</div>
        <div class="user-id">ID #{{ userInfo.id ?? '-' }}</div>
        <el-tag v-if="userInfo.is_active === false" type="danger" size="small" style="margin-top: 8px;">账号已禁用</el-tag>
        <el-divider />
        <div class="info-list">
          <div class="info-row">
            <span class="info-label">邮箱</span>
            <span class="info-value">{{ userInfo.email || '-' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">角色</span>
            <span class="info-value">{{ userInfo.role === 'admin' ? '管理员' : '普通用户' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">注册时间</span>
            <span class="info-value">{{ formatTime(userInfo.created_at) }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">最后登录</span>
            <span class="info-value">{{ formatTime(userInfo.last_login_at) }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">登录IP</span>
            <span class="info-value">{{ userInfo.last_login_ip || '-' }}</span>
          </div>
        </div>
      </div>

      <!-- 右侧设置区 -->
      <div class="settings-card">
        <el-tabs v-model="activeTab">
          <el-tab-pane label="修改邮箱" name="email">
            <el-form ref="emailFormRef" :model="emailForm" :rules="emailRules" label-width="90px" style="max-width: 480px;">
              <el-form-item label="当前邮箱">
                <el-input :model-value="userInfo.email || '-'" disabled />
              </el-form-item>
              <el-form-item label="新邮箱" prop="email">
                <el-input v-model="emailForm.email" placeholder="请输入新邮箱" />
              </el-form-item>
              <el-form-item label="确认邮箱" prop="confirmEmail">
                <el-input v-model="emailForm.confirmEmail" placeholder="请再次输入新邮箱" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="emailLoading" @click="saveEmail">保存邮箱</el-button>
              </el-form-item>
            </el-form>
          </el-tab-pane>

          <el-tab-pane label="修改密码" name="password">
            <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-width="90px" style="max-width: 480px;">
              <el-form-item label="旧密码" prop="oldPassword">
                <el-input v-model="pwdForm.oldPassword" type="password" show-password placeholder="请输入旧密码" />
              </el-form-item>
              <el-form-item label="新密码" prop="newPassword">
                <el-input v-model="pwdForm.newPassword" type="password" show-password placeholder="6-32位，建议字母+数字" />
              </el-form-item>
              <el-form-item label="确认新密码" prop="confirmPassword">
                <el-input v-model="pwdForm.confirmPassword" type="password" show-password placeholder="请再次输入新密码" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="pwdLoading" @click="savePassword">保存密码</el-button>
              </el-form-item>
            </el-form>
          </el-tab-pane>
        </el-tabs>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { getCurrentUser, updateProfile, changePassword, updateUserInfo, clearAuth, authStore } from '../api/index.js'

const router = useRouter()

const userInfo = ref({})
const activeTab = ref('email')
const emailFormRef = ref(null)
const pwdFormRef = ref(null)
const emailLoading = ref(false)
const pwdLoading = ref(false)

const emailForm = reactive({ email: '', confirmEmail: '' })
const pwdForm = reactive({ oldPassword: '', newPassword: '', confirmPassword: '' })

const avatarChar = computed(() => (userInfo.value.username || 'U').charAt(0).toUpperCase())

const emailRules = {
  email: [
    { required: true, message: '请输入新邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' }
  ],
  confirmEmail: [
    { required: true, message: '请再次输入新邮箱', trigger: 'blur' },
    {
      validator: (rule, value, callback) => {
        if (value !== emailForm.email) callback(new Error('两次输入的邮箱不一致'))
        else callback()
      },
      trigger: 'blur'
    }
  ]
}

const pwdRules = {
  oldPassword: [{ required: true, message: '请输入旧密码', trigger: 'blur' }],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, max: 32, message: '密码长度为 6-32 位', trigger: 'blur' }
  ],
  confirmPassword: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (rule, value, callback) => {
        if (value !== pwdForm.newPassword) callback(new Error('两次输入的密码不一致'))
        else callback()
      },
      trigger: 'blur'
    }
  ]
}

function formatTime(s) {
  if (!s) return '-'
  const d = new Date(s)
  return isNaN(d.getTime()) ? s : d.toLocaleString('zh-CN')
}

async function saveEmail() {
  const valid = await emailFormRef.value.validate().catch(() => false)
  if (!valid) return
  emailLoading.value = true
  try {
    const res = await updateProfile({ email: emailForm.email })
    // 同步更新全局用户信息（顶部栏展示）
    updateUserInfo(res.data)
    userInfo.value = res.data
    ElMessage.success('邮箱修改成功')
    emailForm.email = ''
    emailForm.confirmEmail = ''
  } catch (e) {
    ElMessage.error(e.response?.data?.message || e.response?.data?.error || e.response?.data?.detail || '邮箱修改失败')
  } finally {
    emailLoading.value = false
  }
}

async function savePassword() {
  const valid = await pwdFormRef.value.validate().catch(() => false)
  if (!valid) return
  pwdLoading.value = true
  try {
    await changePassword(pwdForm.oldPassword, pwdForm.newPassword)
    ElMessage.success('密码修改成功，请重新登录')
    pwdForm.oldPassword = pwdForm.newPassword = pwdForm.confirmPassword = ''
    // 清除登录态（否则路由守卫会拦截 /login 跳回数据管理），再跳转登录页
    clearAuth()
    router.push('/login')
  } catch (e) {
    ElMessage.error(e.response?.data?.message || e.response?.data?.error || e.response?.data?.detail || '密码修改失败')
  } finally {
    pwdLoading.value = false
  }
}

onMounted(async () => {
  userInfo.value = authStore.user || {}
  try {
    const res = await getCurrentUser()
    userInfo.value = res.data
    updateUserInfo(res.data)
  } catch {
    // 获取用户信息失败时使用本地缓存
  }
})
</script>

<style scoped>
.profile-page {
  padding: 20px;
  max-width: 960px;
}
.page-head {
  margin-bottom: 20px;
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary, #1e293b);
  margin: 0 0 4px 0;
}
.page-sub {
  font-size: 13px;
  color: var(--text-secondary, #64748b);
}
.profile-layout {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 20px;
  align-items: start;
}
.info-card {
  background: #fff;
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 12px;
  padding: 28px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.avatar-box {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--primary-color, #3b82f6);
  color: #fff;
  font-size: 26px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
}
.user-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary, #1e293b);
}
.user-id {
  font-size: 12px;
  color: var(--text-secondary, #64748b);
  margin-top: 2px;
}
.info-list {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.info-label {
  font-size: 13px;
  color: var(--text-secondary, #64748b);
  flex-shrink: 0;
}
.info-value {
  font-size: 13px;
  color: var(--text-primary, #1e293b);
  text-align: right;
  word-break: break-all;
}
.settings-card {
  background: #fff;
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 12px;
  padding: 20px 24px;
  min-height: 320px;
}
@media (max-width: 768px) {
  .profile-layout {
    grid-template-columns: 1fr;
  }
}
</style>
