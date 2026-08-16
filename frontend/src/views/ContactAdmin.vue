<template>
  <div class="contact-page">
    <div class="contact-card">
      <!-- 头部 -->
      <div class="head">
        <el-button text size="small" class="back-btn" @click="$router.push('/')" aria-label="返回首页">
          <el-icon style="margin-right: 4px;"><ArrowLeft /></el-icon>返回首页
        </el-button>
        <h2 class="page-title">联系管理员</h2>
        <p class="page-sub">无需登录即可提交申请，管理员处理后会在「用户申请」中跟进</p>
      </div>

      <!-- 功能选择卡片 -->
      <div class="func-cards">
        <div
          v-for="f in funcs"
          :key="f.value"
          class="func-card"
          :class="{ active: activeFunc === f.value }"
          @click="switchFunc(f.value)"
        >
          <div class="func-icon"><el-icon :size="22"><component :is="f.icon" /></el-icon></div>
          <div class="func-title">{{ f.label }}</div>
          <div class="func-desc">{{ f.desc }}</div>
        </div>
      </div>

      <!-- 表单 -->
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="100px" class="form-area">
        <!-- 恢复永久删除数据集 -->
        <template v-if="activeFunc === 'restore_dataset'">
          <el-form-item label="用户名" prop="username">
            <el-input v-model="form.username" placeholder="请输入您的用户名" maxlength="100" />
          </el-form-item>
          <el-form-item label="数据集名称" prop="datasetName">
            <el-input v-model="form.datasetName" placeholder="请输入被删除的数据集名称（支持关键字）" maxlength="200" />
          </el-form-item>
          <el-form-item label="补充说明" prop="description">
            <el-input v-model="form.description" type="textarea" :rows="3" placeholder="例如：误点清空回收站，希望找回该数据" maxlength="500" />
          </el-form-item>
        </template>

        <!-- 解锁账户 -->
        <template v-else-if="activeFunc === 'unlock'">
          <el-form-item label="用户名" prop="username">
            <el-input v-model="form.username" placeholder="请输入被锁定的用户名" maxlength="100" />
          </el-form-item>
          <el-form-item label="联系方式" prop="contact">
            <el-input v-model="form.contact" placeholder="邮箱或手机号，便于管理员联系您" maxlength="200" />
          </el-form-item>
          <el-form-item label="补充说明" prop="description">
            <el-input v-model="form.description" type="textarea" :rows="3" placeholder="例如：登录失败次数过多被锁定，本人为账号合法使用者" maxlength="500" />
          </el-form-item>
        </template>

        <!-- 系统错误上报 -->
        <template v-else>
          <el-form-item label="用户名" prop="username">
            <el-input v-model="form.username" placeholder="请输入您的用户名（选填）" maxlength="100" />
          </el-form-item>
          <el-form-item label="错误描述" prop="description">
            <el-input v-model="form.description" type="textarea" :rows="3" placeholder="请描述遇到的问题，例如：远程数据挖掘执行报错" maxlength="500" />
          </el-form-item>
          <el-form-item label="复现步骤" prop="steps">
            <el-input v-model="form.steps" type="textarea" :rows="2" placeholder="如何复现该问题（选填）" maxlength="500" />
          </el-form-item>
          <el-form-item label="截图">
            <el-upload
              :auto-upload="false"
              :limit="1"
              list-type="picture-card"
              accept=".jpg,.jpeg,.png,.gif,.webp"
              :on-change="onFileChange"
              :on-remove="onFileRemove"
            >
              <el-icon><Plus /></el-icon>
            </el-upload>
            <div v-if="uploadError" class="upload-error">{{ uploadError }}</div>
            <div class="upload-hint">支持 jpg/png/gif/webp，不超过 5MB</div>
          </el-form-item>
          <el-form-item label="联系方式" prop="contact">
            <el-input v-model="form.contact" placeholder="邮箱或手机号（选填）" maxlength="200" />
          </el-form-item>
        </template>

        <!-- 验证码 -->
        <el-form-item label="验证码" prop="captchaAnswer">
          <div class="captcha-row">
            <div class="captcha-box">{{ captcha.question || '加载中…' }}</div>
            <el-button text type="primary" @click="loadCaptcha" aria-label="刷新验证码">换一题</el-button>
            <el-input v-model="form.captchaAnswer" placeholder="输入答案" style="width: 150px;" maxlength="4" />
          </div>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="submitting" @click="submit">提交申请</el-button>
          <span class="rate-hint">同一 IP / 用户名在限定时长内仅可提交 1 次，超出后按提示等待</span>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { FolderOpened, Lock, Warning, Plus, ArrowLeft } from '@element-plus/icons-vue'
import { getSupportCaptcha, uploadSupportImage, submitSupportMessage } from '../api/index.js'

const funcs = [
  { value: 'restore_dataset', label: '恢复永久删除数据集', desc: '误删后需要找回已清空的数据', icon: FolderOpened },
  { value: 'unlock', label: '解锁账户', desc: '登录失败次数过多被锁定', icon: Lock },
  { value: 'error_report', label: '系统错误上报', desc: '使用平台时遇到 Bug 或异常', icon: Warning }
]

const activeFunc = ref('restore_dataset')
const formRef = ref(null)
const submitting = ref(false)

// 验证码
const captcha = ref({ captcha_id: '', question: '' })
// 截图上传
const attachmentPath = ref('')
const attachmentName = ref('')
const uploadError = ref('')

const form = reactive({
  username: '',
  contact: '',
  datasetName: '',
  description: '',
  steps: '',
  captchaAnswer: ''
})

function switchFunc(value) {
  activeFunc.value = value
  formRef.value?.clearValidate()
}

async function loadCaptcha() {
  try {
    const res = await getSupportCaptcha()
    captcha.value = res.data
    form.captchaAnswer = ''
  } catch {
    ElMessage.error('验证码加载失败，请稍后重试')
  }
}

async function onFileChange(file) {
  uploadError.value = ''
  try {
    const res = await uploadSupportImage(file.raw)
    attachmentPath.value = res.data.path
    attachmentName.value = res.data.name
  } catch (e) {
    uploadError.value = e.response?.data?.message || e.response?.data?.error || '图片上传失败'
    file.status = 'fail'
    // 移除失败的文件，避免残留
    const uploadEl = document.querySelector('.el-upload-list__item.is-fail')
    if (uploadEl) uploadEl.remove()
  }
}

function onFileRemove() {
  attachmentPath.value = ''
  attachmentName.value = ''
}

const formRules = computed(() => {
  const rules = {}
  if (activeFunc.value === 'restore_dataset') {
    rules.username = [{ required: true, message: '请输入用户名', trigger: 'blur' }]
    rules.datasetName = [{ required: true, message: '请输入数据集名称', trigger: 'blur' }]
  } else if (activeFunc.value === 'unlock') {
    rules.username = [{ required: true, message: '请输入用户名', trigger: 'blur' }]
    rules.contact = [{ required: true, message: '请输入联系方式', trigger: 'blur' }]
  } else {
    rules.description = [{ required: true, message: '请输入错误描述', trigger: 'blur' }]
  }
  rules.captchaAnswer = [{ required: true, message: '请输入验证码答案', trigger: 'blur' }]
  return rules
})

async function submit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  if (!captcha.value.captcha_id) {
    ElMessage.warning('请先刷新验证码')
    return
  }

  // 按分类构建内容
  const content = { description: form.description }
  if (activeFunc.value === 'restore_dataset') content.dataset_name = form.datasetName
  if (activeFunc.value === 'error_report') content.steps = form.steps

  submitting.value = true
  try {
    const payload = {
      category: activeFunc.value,
      username: form.username,
      contact: form.contact,
      content,
      captcha_id: captcha.value.captcha_id,
      captcha_answer: form.captchaAnswer
    }
    // 错误上报才有截图
    if (activeFunc.value === 'error_report' && attachmentPath.value) {
      payload.attachment_path = attachmentPath.value
      payload.attachment_name = attachmentName.value
    }
    const res = await submitSupportMessage(payload)
    ElMessage.success(res.data.message || '申请已提交，管理员将尽快处理')
    // 重置表单与验证码
    form.username = ''
    form.contact = ''
    form.datasetName = ''
    form.description = ''
    form.steps = ''
    form.captchaAnswer = ''
    attachmentPath.value = ''
    attachmentName.value = ''
    formRef.value?.clearValidate()
    loadCaptcha()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || e.response?.data?.error || e.response?.data?.detail || '提交失败，请稍后重试')
    // 验证码一次性使用，提交失败后刷新
    loadCaptcha()
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  loadCaptcha()
})
</script>

<style scoped>
.contact-page {
  padding: 24px 16px 40px;
  display: flex;
  justify-content: center;
}
.contact-card {
  width: 100%;
  max-width: 720px;
  background: #fff;
  border-radius: 12px;
  padding: 28px 32px 32px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  height: fit-content;
}
.head {
  margin-bottom: 24px;
}
.back-btn {
  margin-left: -8px;
  margin-bottom: 8px;
  color: var(--text-secondary, #64748b);
}
.page-title {
  font-size: 22px;
  font-weight: 600;
  color: var(--text-primary, #1e293b);
  margin: 0 0 6px 0;
}
.page-sub {
  font-size: 13px;
  color: var(--text-secondary, #64748b);
  margin: 0;
}
.func-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}
.func-card {
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 10px;
  padding: 16px 14px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  background: #fff;
}
.func-card:hover {
  border-color: var(--primary, #3b82f6);
}
.func-card.active {
  border-color: var(--primary, #3b82f6);
  background: #f0f7ff;
}
.func-icon {
  color: var(--primary, #3b82f6);
  margin-bottom: 8px;
}
.func-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #1e293b);
  margin-bottom: 4px;
}
.func-desc {
  font-size: 12px;
  color: var(--text-secondary, #64748b);
}
.form-area {
  max-width: 560px;
}
.captcha-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.captcha-box {
  width: 110px;
  height: 32px;
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 6px;
  background: #f8fafc;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  color: var(--primary, #3b82f6);
  letter-spacing: 1px;
  user-select: none;
}
.rate-hint {
  font-size: 12px;
  color: var(--text-secondary, #64748b);
  margin-left: 12px;
}
.upload-error {
  font-size: 12px;
  color: #e8463a;
  margin-top: 6px;
}
.upload-hint {
  font-size: 12px;
  color: var(--text-secondary, #64748b);
  margin-top: 6px;
}
@media (max-width: 640px) {
  .func-cards {
    grid-template-columns: 1fr;
  }
}
</style>
