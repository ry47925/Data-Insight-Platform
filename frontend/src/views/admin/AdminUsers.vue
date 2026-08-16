<template>
  <div>
    <!-- 统计卡片 -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">用户统计</div>
        <div class="flex-center" style="gap:10px;">
          <span class="text-sm" style="color: #9ca3af;">自动刷新</span>
          <el-switch v-model="autoRefresh" @change="autoRefresh ? startAutoRefresh() : stopAutoRefresh()" />
          <el-button size="small" @click="immediateRefresh">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
        </div>
      </div>
      <div class="stats-grid" style="grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));">
        <div class="stat-card">
          <div class="stat-value">{{ stats.total_users || 0 }}</div>
          <div class="stat-label">总用户数</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ stats.active_today || 0 }}</div>
          <div class="stat-label">今日活跃</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ stats.disabled_users || 0 }}</div>
          <div class="stat-label">已禁用账号</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ stats.locked_users || 0 }}</div>
          <div class="stat-label">已锁定账号</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ stats.total_datasets || 0 }}</div>
          <div class="stat-label">总数据集</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ formatSize(stats.total_storage_bytes) }}</div>
          <div class="stat-label">总存储量</div>
        </div>
      </div>
      <!-- 近 30 天注册趋势 -->
      <div ref="regTrendRef" style="height: 260px; margin-top: 16px;"></div>
    </div>

    <!-- Tab 切换 -->
    <el-tabs v-model="activeTab" class="admin-tabs">
      <!-- ===== Tab1 用户列表 ===== -->
      <el-tab-pane label="用户列表" name="users">
        <div class="card">
          <div class="card-header">
            <div class="card-title">用户列表</div>
            <div class="flex-center" style="gap:10px;">
              <el-input v-model="searchQuery" placeholder="搜索用户名/邮箱" clearable style="width:200px;" @keyup.enter="loadUsers" @clear="loadUsers" />
              <el-select v-model="statusFilter" placeholder="状态筛选" clearable style="width:120px;" @change="loadUsers">
                <el-option label="启用" value="active" />
                <el-option label="禁用" value="disabled" />
                <el-option label="锁定" value="locked" />
              </el-select>
              <el-button size="small" type="primary" @click="loadUsers">
                <el-icon><Search /></el-icon> 查询
              </el-button>
            </div>
          </div>
          <div class="data-table-wrapper">
            <el-table :data="users" border v-loading="loading">
              <el-table-column prop="id" label="ID" width="60" />
              <el-table-column prop="username" label="用户名" min-width="110" />
              <el-table-column prop="email" label="邮箱" min-width="160" show-overflow-tooltip />
              <el-table-column label="状态" width="88" align="center">
                <template #default="scope">
                  <el-tag :type="getStatusTagType(scope.row)" size="small">{{ getStatusLabel(scope.row) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="注册时间" width="170">
                <template #default="scope">
                  {{ formatTime(scope.row.created_at) }}
                </template>
              </el-table-column>
              <el-table-column label="最后登录" width="170">
                <template #default="scope">
                  {{ formatTime(scope.row.last_login_at) }}
                </template>
              </el-table-column>
              <el-table-column prop="last_login_ip" label="登录IP" width="125" />
              <el-table-column prop="dataset_count" label="数据集" width="72" align="center" />
              <el-table-column label="存储大小" width="95">
                <template #default="scope">
                  {{ formatSize(scope.row.total_storage_bytes) }}
                </template>
              </el-table-column>
              <el-table-column prop="task_count" label="任务数" width="70" align="center" />
              <el-table-column label="操作" width="205" align="center" fixed="right">
                <template #default="scope">
                  <el-button size="small" link type="primary" @click="openDetail(scope.row)" aria-label="查看详情">详情</el-button>
                  <el-button size="small" link type="primary" @click="openResetDialog(scope.row)" aria-label="重置密码">重置密码</el-button>
                  <el-button v-if="scope.row.is_locked" size="small" link type="warning" @click="openActionConfirm(scope.row, 'unlock')" aria-label="解锁账号">解锁</el-button>
                  <el-button v-else-if="scope.row.is_active" size="small" link type="danger" @click="openActionConfirm(scope.row, 'disable')" aria-label="禁用账号">禁用</el-button>
                  <el-button v-else size="small" link type="success" @click="openActionConfirm(scope.row, 'enable')" aria-label="启用账号">启用</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div class="flex-center" style="justify-content: flex-end; margin-top: 16px;">
            <el-pagination
              v-model:current-page="page"
              :page-size="pageSize"
              :total="total"
              layout="total, prev, pager, next"
              @current-change="loadUsers"
            />
          </div>
        </div>
      </el-tab-pane>

      <!-- ===== Tab2 用户申请 ===== -->
      <el-tab-pane label="用户申请" name="messages">
        <div class="card">
          <div class="card-header">
            <div class="card-title">用户申请<span v-if="pendingCount > 0" class="pending-badge">{{ pendingCount }}</span></div>
            <div class="flex-center" style="gap:10px;">
              <el-select v-model="msgCategory" placeholder="分类" clearable style="width:130px;" @change="loadMessages">
                <el-option label="恢复数据集" value="restore_dataset" />
                <el-option label="解锁账户" value="unlock" />
                <el-option label="错误上报" value="error_report" />
              </el-select>
              <el-select v-model="msgStatus" placeholder="状态" clearable style="width:120px;" @change="loadMessages">
                <el-option label="待处理" value="pending" />
                <el-option label="已处理" value="done" />
              </el-select>
              <el-input v-model="msgKeyword" placeholder="搜索申请人/联系方式" clearable style="width:180px;" @keyup.enter="loadMessages" @clear="loadMessages" />
              <el-button size="small" type="primary" @click="loadMessages">
                <el-icon><Search /></el-icon> 查询
              </el-button>
            </div>
          </div>
          <div class="data-table-wrapper">
            <el-table :data="messages" border v-loading="messagesLoading">
              <el-table-column prop="id" label="ID" width="60" />
              <el-table-column label="分类" width="100">
                <template #default="scope">
                  <el-tag size="small" effect="plain">{{ scope.row.category_label }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="username" label="申请人" width="100">
                <template #default="scope">{{ scope.row.username || '-' }}</template>
              </el-table-column>
              <el-table-column prop="content_summary" label="内容摘要" min-width="180" show-overflow-tooltip>
                <template #default="scope">{{ scope.row.content_summary || scope.row.contact || '-' }}</template>
              </el-table-column>
              <el-table-column label="状态" width="90" align="center">
                <template #default="scope">
                  <el-tag size="small" :type="scope.row.status === 'done' ? 'success' : 'warning'">{{ scope.row.status_label }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="提交时间" width="170">
                <template #default="scope">{{ formatTime(scope.row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="120" align="center" fixed="right">
                <template #default="scope">
                  <el-button size="small" link type="primary" @click="openMessageDetail(scope.row)" aria-label="处理申请">
                    {{ scope.row.status === 'done' ? '查看' : '处理' }}
                  </el-button>
                  <el-button size="small" link type="danger" @click="openMessageDelete(scope.row)" aria-label="删除申请">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div class="flex-center" style="justify-content: flex-end; margin-top: 16px;">
            <el-pagination
              v-model:current-page="msgPage"
              :page-size="msgPageSize"
              :total="msgTotal"
              layout="total, prev, pager, next"
              @current-change="loadMessages"
            />
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 用户详情弹窗 -->
    <el-dialog v-model="detailVisible" :title="`用户详情 — ${detailUser?.username || ''}`" width="780px" top="6vh" destroy-on-close aria-label="用户详情弹窗">
      <el-tabs v-model="detailTab">
        <el-tab-pane label="基本信息" name="info">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="用户名">{{ detailUser?.username }}</el-descriptions-item>
            <el-descriptions-item label="邮箱">{{ detailUser?.email || '-' }}</el-descriptions-item>
            <el-descriptions-item label="账号状态">
              <el-tag :type="getStatusTagType(detailUser)" size="small">{{ getStatusLabel(detailUser) }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="登录IP">{{ detailUser?.last_login_ip || '-' }}</el-descriptions-item>
            <el-descriptions-item label="注册时间">{{ formatTime(detailUser?.created_at) }}</el-descriptions-item>
            <el-descriptions-item label="最后登录">{{ formatTime(detailUser?.last_login_at) }}</el-descriptions-item>
            <el-descriptions-item label="数据集数">{{ detailUser?.dataset_count || 0 }}</el-descriptions-item>
            <el-descriptions-item label="存储大小">{{ formatSize(detailUser?.total_storage_bytes) }}</el-descriptions-item>
            <el-descriptions-item label="任务数">{{ detailUser?.task_count || 0 }}</el-descriptions-item>
            <el-descriptions-item v-if="detailUser?.is_locked" label="锁定截止">{{ formatTime(detailUser?.locked_until) }}</el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
        <el-tab-pane label="数据集" name="datasets">
          <el-table :data="detailDatasets" border size="small" v-loading="detailLoading">
            <el-table-column prop="name" label="名称" min-width="170" show-overflow-tooltip />
            <el-table-column prop="module_label" label="模块" width="105" />
            <el-table-column prop="artifact_type" label="类型" width="105" />
            <el-table-column prop="row_count" label="行数" width="75" align="center" />
            <el-table-column label="大小" width="90">
              <template #default="scope">{{ formatSize(scope.row.file_size) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="80" align="center">
              <template #default="scope">
                <el-tag size="small" :type="datasetStatusType(scope.row.status)">{{ datasetStatusLabel(scope.row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="创建时间" width="165">
              <template #default="scope">{{ formatTime(scope.row.created_at) }}</template>
            </el-table-column>
          </el-table>
          <div v-if="!detailLoading && detailDatasets.length === 0" style="text-align:center; color:#9ca3af; padding:20px;">该用户暂无数据集</div>
        </el-tab-pane>
        <el-tab-pane label="操作历史" name="tasks">
          <el-table :data="detailTasks" border size="small" v-loading="detailLoading">
            <el-table-column prop="task_type" label="任务类型" width="115" />
            <el-table-column prop="detail" label="操作说明" min-width="230" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="80" align="center" />
            <el-table-column label="时间" width="165">
              <template #default="scope">{{ formatTime(scope.row.created_at) }}</template>
            </el-table-column>
          </el-table>
          <div v-if="!detailLoading && detailTasks.length === 0" style="text-align:center; color:#9ca3af; padding:20px;">该用户暂无操作记录</div>
        </el-tab-pane>
      </el-tabs>
    </el-dialog>

    <!-- 禁用/启用/解锁确认弹窗 -->
    <el-dialog v-model="actionVisible" title="操作确认" width="440px" aria-label="账号操作确认弹窗">
      <div style="text-align:center; padding: 20px 0;">
        <el-icon :size="60" :style="{ color: actionTarget?.action === 'disable' ? '#f56c6c' : '#e6a23c', marginBottom: '16px' }"><Warning /></el-icon>
        <p style="font-size: 15px; color: var(--text-primary); margin-bottom: 8px;">{{ actionMessage }}</p>
        <p style="font-size: 13px; color: var(--text-secondary);">
          用户：<strong>{{ actionTarget?.user?.username }}</strong>（#{{ actionTarget?.user?.id }}）
        </p>
        <p v-if="actionTarget?.action === 'disable'" style="font-size: 13px; color: var(--text-secondary); margin-top: 4px;">
          禁用后该用户将无法登录，已登录会话立即失效
        </p>
        <p v-else-if="actionTarget?.action === 'enable'" style="font-size: 13px; color: var(--text-secondary); margin-top: 4px;">
          启用后该用户可正常登录，失败计数与锁定状态将被清除
        </p>
        <p v-else-if="actionTarget?.action === 'unlock'" style="font-size: 13px; color: var(--text-secondary); margin-top: 4px;">
          解锁后用户可立即重新登录，无需等待锁定时间结束
        </p>
      </div>
      <template #footer>
        <el-button @click="actionVisible = false" aria-label="取消操作">取消</el-button>
        <el-button :type="actionTarget?.action === 'disable' ? 'danger' : 'primary'" @click="executeAction" :loading="actionLoading" aria-label="确认操作">
          {{ actionButtonLabel }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 重置密码弹窗 -->
    <el-dialog v-model="resetVisible" title="重置密码" width="460px" aria-label="重置密码弹窗">
      <div v-if="!resetResult">
        <p style="font-size: 13px; color: var(--text-secondary); margin-bottom: 12px;">
          为用户 <strong>{{ resetTarget?.username }}</strong>（#{{ resetTarget?.id }}）设置新密码。留空将自动生成随机密码。
        </p>
        <el-input v-model="newPassword" type="password" show-password placeholder="输入新密码（至少6位，留空自动生成）" aria-label="新密码输入" />
      </div>
      <div v-else style="text-align:center; padding: 10px 0;">
        <el-icon :size="52" style="color: #67c23a; margin-bottom: 12px;"><SuccessFilled /></el-icon>
        <p style="font-size: 15px; color: var(--text-primary); margin-bottom: 12px;">密码已重置成功</p>
        <div style="background: #f5f7fa; border-radius: 6px; padding: 12px; margin-bottom: 8px;">
          <div style="font-size: 13px; color: #9ca3af; margin-bottom: 4px;">新密码（请立即告知用户，仅显示一次）</div>
          <div style="font-size: 18px; font-weight: 600; font-family: monospace; word-break: break-all;">{{ resetResult }}</div>
        </div>
      </div>
      <template #footer>
        <template v-if="!resetResult">
          <el-button @click="resetVisible = false" aria-label="取消重置">取消</el-button>
          <el-button type="primary" @click="executeReset" :loading="resetLoading" aria-label="确认重置">确认重置</el-button>
        </template>
        <el-button v-else type="primary" @click="resetVisible = false; resetResult = ''" aria-label="关闭">我已记录，关闭</el-button>
      </template>
    </el-dialog>

    <!-- 用户申请处理弹窗 -->
    <el-dialog v-model="messageDetailVisible" :title="`申请处理 — ${messageDetail?.category_label || ''} #${messageDetail?.id}`" width="760px" top="6vh" destroy-on-close aria-label="申请处理弹窗">
      <div v-if="messageDetail" class="message-detail">
        <!-- 申请信息 -->
        <el-descriptions :column="2" border>
          <el-descriptions-item label="分类">
            <el-tag size="small" effect="plain">{{ messageDetail.category_label }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag size="small" :type="messageDetail.status === 'done' ? 'success' : 'warning'">{{ messageDetail.status_label }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="申请人">{{ messageDetail.username || '-' }}</el-descriptions-item>
          <el-descriptions-item label="联系方式">{{ messageDetail.contact || '-' }}</el-descriptions-item>
          <el-descriptions-item label="提交时间">{{ formatTime(messageDetail.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="来源IP">{{ messageDetail.client_ip || '-' }}</el-descriptions-item>
        </el-descriptions>

        <!-- 申请人账号核实 -->
        <div class="op-section">
          <div class="op-head">申请人账号核实</div>
          <div v-if="applicantInfo" class="applicant-info">
            <div class="applicant-row">
              <span class="msg-label">账号</span>
              <span>{{ applicantInfo.username }}（#{{ applicantInfo.id }}）</span>
              <el-tag size="small" :type="applicantInfo.is_locked ? 'warning' : applicantInfo.is_active ? 'success' : 'danger'">
                {{ applicantInfo.is_locked ? '已锁定' : applicantInfo.is_active ? '启用' : '已禁用' }}
              </el-tag>
            </div>
            <div class="applicant-row"><span class="msg-label">注册时间</span><span>{{ formatTime(applicantInfo.created_at) }}</span></div>
            <div class="applicant-row"><span class="msg-label">账号数据</span><span>{{ applicantInfo.dataset_count }} 个数据集 · {{ applicantInfo.task_count }} 次任务</span></div>
          </div>
          <div v-else-if="applicantNotFound" class="candidate-empty">
            ⚠️ 系统中未找到用户名「{{ messageDetail.username }}」，请谨慎核实申请人身份后再处理
          </div>
          <div v-else class="candidate-empty">未填写用户名或未查询到账号信息</div>
        </div>

        <!-- 分类内容 -->
        <div class="msg-content">
          <template v-if="messageDetail.category === 'restore_dataset'">
            <div class="msg-row"><span class="msg-label">数据集名称</span><span>{{ messageDetail.content?.dataset_name || '-' }}</span></div>
            <div class="msg-row"><span class="msg-label">补充说明</span><span>{{ messageDetail.content?.description || '-' }}</span></div>
          </template>
          <template v-else-if="messageDetail.category === 'unlock'">
            <div class="msg-row"><span class="msg-label">补充说明</span><span>{{ messageDetail.content?.description || '-' }}</span></div>
          </template>
          <template v-else>
            <div class="msg-row"><span class="msg-label">错误描述</span><span>{{ messageDetail.content?.description || '-' }}</span></div>
            <div class="msg-row"><span class="msg-label">复现步骤</span><span>{{ messageDetail.content?.steps || '-' }}</span></div>
            <div v-if="messageDetail.attachment_path" class="msg-row">
              <span class="msg-label">截图</span>
              <div class="attachment-area">
                <img v-if="attachmentUrl" :src="attachmentUrl" class="attachment-img" alt="错误上报截图" />
                <span v-else class="attachment-loading">加载中…</span>
                <el-button v-if="attachmentUrl" size="small" link type="primary" @click="downloadAttachment" aria-label="下载截图">下载原图</el-button>
              </div>
            </div>
          </template>
        </div>

        <!-- 分类专属操作 -->
        <div v-if="messageDetail.status !== 'done'" class="op-section">
          <template v-if="messageDetail.category === 'unlock'">
            <div class="op-head">解锁账户</div>
            <div class="op-body">
              <div class="flex-center" style="gap:8px; margin-bottom: 10px;">
                <el-input v-model="userSearch" placeholder="输入用户名查询该账号" style="width:220px;" @keyup.enter="searchUser()" />
                <el-button size="small" @click="searchUser()">查询</el-button>
              </div>
              <div v-if="userCandidates.length" class="candidate-list">
                <div v-for="u in userCandidates" :key="u.id" class="candidate-row">
                  <span>{{ u.username }}（#{{ u.id }}）</span>
                  <el-tag size="small" :type="u.is_locked ? 'warning' : u.is_active ? 'success' : 'danger'">
                    {{ u.is_locked ? '已锁定' : u.is_active ? '正常' : '已禁用' }}
                  </el-tag>
                  <el-button v-if="u.is_locked" size="small" type="warning" :loading="unlockLoading" @click="doUnlockUser(u)">一键解锁</el-button>
                </div>
                <div v-if="!userCandidates[0]?.is_locked" class="candidate-empty">该账号当前未锁定，无需解锁</div>
              </div>
            </div>
          </template>
          <template v-else-if="messageDetail.category === 'restore_dataset'">
            <div class="op-head">恢复数据集</div>
            <div class="op-body">
              <div class="flex-center" style="gap:8px; margin-bottom: 10px;">
                <el-input v-model="dsSearch" placeholder="输入关键字搜索已清空(purged)数据集" style="width:260px;" @keyup.enter="searchDatasets(dsScope)" />
                <el-button size="small" @click="searchDatasets(dsScope)">搜索</el-button>
              </div>
              <div v-if="dsCandidates.length" class="candidate-list">
                <div v-for="d in dsCandidates" :key="d.id" class="candidate-row">
                  <div class="candidate-main">
                    <span>{{ d.name }}</span>
                    <el-tag size="small" :type="applicantInfo && d.user_id === applicantInfo.id ? 'success' : 'danger'">
                      {{ applicantInfo && d.user_id === applicantInfo.id ? '申请人名下' : '非申请人名下' }}
                    </el-tag>
                    <span class="candidate-meta">#{{ d.id }} · {{ d.username }}</span>
                  </div>
                  <el-button size="small" type="primary" :loading="restoreLoading" @click="doRestoreDataset(d)">一键恢复</el-button>
                </div>
              </div>
              <div v-else class="candidate-empty">未找到匹配的已清空数据集。可在「数据管理-已清空」中按关键字搜索确认</div>
            </div>
          </template>
        </div>

        <!-- 处理备注 -->
        <div class="note-section">
          <div class="op-head">处理备注</div>
          <el-input v-model="adminNote" type="textarea" :rows="2" :disabled="messageDetail.status === 'done'" placeholder="填写处理结果或说明" maxlength="500" />
          <div v-if="messageDetail.status === 'done' && messageDetail.admin_note" class="msg-row" style="margin-top:8px;">
            <span class="msg-label">历史备注</span><span>{{ messageDetail.admin_note }}</span>
          </div>
          <div v-if="messageDetail.status === 'done' && messageDetail.processed_at" class="msg-row">
            <span class="msg-label">处理时间</span><span>{{ formatTime(messageDetail.processed_at) }}</span>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button type="danger" plain :disabled="messageDetail?.status === 'done'" @click="openMessageDelete(messageDetail)" aria-label="删除申请">删除申请</el-button>
        <el-button @click="messageDetailVisible = false" aria-label="关闭">关闭</el-button>
        <el-button v-if="messageDetail?.status !== 'done'" type="primary" :loading="processLoading" @click="confirmProcess" aria-label="标记已处理">标记已处理</el-button>
      </template>
    </el-dialog>

    <!-- 申请删除确认弹窗 -->
    <el-dialog v-model="messageDeleteVisible" title="删除确认" width="440px" aria-label="申请删除确认弹窗">
      <div style="text-align:center; padding: 20px 0;">
        <el-icon :size="60" style="color: #f56c6c; margin-bottom: 16px;"><Warning /></el-icon>
        <p style="font-size: 15px; color: var(--text-primary); margin-bottom: 8px;">
          确定要删除申请 <strong>#{{ messageDeleteTarget?.id }}</strong>（{{ messageDeleteTarget?.category_label }}）吗？
        </p>
        <p style="font-size: 13px; color: var(--text-secondary);">
          删除后不可恢复，关联截图文件将一并清理
        </p>
      </div>
      <template #footer>
        <el-button @click="messageDeleteVisible = false" aria-label="取消删除">取消</el-button>
        <el-button type="danger" :loading="messageDeleteLoading" @click="confirmDeleteMessage" aria-label="确认删除">确认删除</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Search, Refresh, Warning, SuccessFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import {
  listUsers,
  getUsersStats,
  updateUserStatus,
  resetUserPassword,
  unlockUser,
  listBusinessDatasets,
  listBusinessTasks,
  restorePurgedDataset,
  listSupportMessages,
  processSupportMessage,
  deleteSupportMessage,
  downloadStorageFile
} from '../../api/admin.js'
import { useAutoRefresh } from '../../composables/useAutoRefresh.js'

// ===== Tab =====
const activeTab = ref('users')

// ===== 用户列表 =====
const stats = ref({})
const regTrendRef = ref(null)
let regTrendChart = null
const users = ref([])
const loading = ref(false)
const searchQuery = ref('')
const statusFilter = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

// 自动刷新
const { autoRefresh, immediateRefresh, startAutoRefresh, stopAutoRefresh } = useAutoRefresh(loadAll)

// 用户详情弹窗
const detailVisible = ref(false)
const detailTab = ref('info')
const detailUser = ref(null)
const detailDatasets = ref([])
const detailTasks = ref([])
const detailLoading = ref(false)

// 禁用/启用/解锁确认
const actionVisible = ref(false)
const actionTarget = ref(null)
const actionLoading = ref(false)

// 重置密码
const resetVisible = ref(false)
const resetTarget = ref(null)
const newPassword = ref('')
const resetResult = ref('')
const resetLoading = ref(false)

// ===== 用户申请 =====
const messages = ref([])
const messagesLoading = ref(false)
const msgCategory = ref('')
const msgStatus = ref('')
const msgKeyword = ref('')
const msgPage = ref(1)
const msgPageSize = ref(20)
const msgTotal = ref(0)

// 申请处理弹窗
const messageDetailVisible = ref(false)
const messageDetail = ref(null)
const processLoading = ref(false)
const adminNote = ref('')
const attachmentUrl = ref('')
// 分类专属操作
const userSearch = ref('')
const userCandidates = ref([])
const unlockLoading = ref(false)
// 申请人账号核实
const applicantInfo = ref(null)
const applicantNotFound = ref(false)
const dsSearch = ref('')
const dsCandidates = ref([])
const dsScope = ref(null)  // 恢复搜索范围：申请人 user_id，null=全部用户
const restoreLoading = ref(false)
// 申请删除确认
const messageDeleteVisible = ref(false)
const messageDeleteTarget = ref(null)
const messageDeleteLoading = ref(false)

const pendingCount = computed(() => {
  // 仅当未筛选状态时展示总待处理数（简化：直接统计当前加载页 pending 数不可靠，改为后端统计可后续增强）
  return 0
})

function formatSize(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(2) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(2) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB'
}

function formatTime(dateStr) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  if (isNaN(date.getTime())) return dateStr
  return date.toLocaleString('zh-CN')
}

// 账号状态：锁定优先于禁用/启用展示
function getStatusTagType(row) {
  if (!row) return 'info'
  if (row.is_locked) return 'warning'
  return row.is_active ? 'success' : 'danger'
}

function getStatusLabel(row) {
  if (!row) return '-'
  if (row.is_locked) return '已锁定'
  return row.is_active ? '启用' : '禁用'
}

function datasetStatusType(s) {
  return { active: 'success', deleted: 'info', purged: 'danger', corrupted: 'danger' }[s] || 'info'
}

function datasetStatusLabel(s) {
  return { active: '正常', deleted: '回收站', purged: '已清空', corrupted: '已损坏' }[s] || s
}

async function loadStats() {
  try {
    const res = await getUsersStats()
    stats.value = res.data
    renderRegTrend()
  } catch (e) {
    console.error('获取用户统计失败:', e)
  }
}

// 近 30 天注册趋势图（数据来自 /users/stats.registration_trend）
function renderRegTrend() {
  const trend = stats.value.registration_trend
  if (!trend || !regTrendRef.value) return
  if (!regTrendChart) {
    regTrendChart = echarts.init(regTrendRef.value)
  }
  regTrendChart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: '4%', right: '4%', bottom: '6%', top: '10%', containLabel: true },
    xAxis: { type: 'category', data: trend.map(x => x.date), boundaryGap: false },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{
      name: '新增注册', type: 'bar',
      data: trend.map(x => x.value),
      itemStyle: { color: '#3b82f6', borderRadius: [3, 3, 0, 0] }, barMaxWidth: 14,
    }],
  })
}

async function loadUsers() {
  loading.value = true
  try {
    const params = { search: searchQuery.value, page: page.value, page_size: pageSize.value }
    if (statusFilter.value) params.status = statusFilter.value
    const res = await listUsers(params)
    users.value = res.data.users || []
    total.value = res.data.total || 0
  } catch (e) {
    console.error('获取用户列表失败:', e)
  } finally {
    loading.value = false
  }
}

async function loadAll() {
  await Promise.all([loadStats(), loadUsers()])
}

// ===== 用户详情下钻 =====
async function openDetail(row) {
  detailUser.value = row
  detailVisible.value = true
  detailTab.value = 'info'
  await loadDetailData(row.id)
}

async function loadDetailData(userId) {
  detailLoading.value = true
  detailDatasets.value = []
  detailTasks.value = []
  try {
    // 复用业务数据/任务历史接口，按 user_id 下钻
    const [dsRes, tkRes] = await Promise.all([
      listBusinessDatasets({ user_id: userId, page: 1, page_size: 50 }),
      listBusinessTasks({ user_id: userId, page: 1, page_size: 50 })
    ])
    detailDatasets.value = dsRes.data.datasets || []
    detailTasks.value = tkRes.data.tasks || []
  } catch (e) {
    console.error('加载用户详情失败:', e)
  } finally {
    detailLoading.value = false
  }
}

// ===== 禁用/启用/解锁 =====
function openActionConfirm(row, action) {
  actionTarget.value = { user: row, action }
  actionVisible.value = true
}

const actionMessage = computed(() => {
  if (!actionTarget.value) return ''
  const u = actionTarget.value.user
  return {
    disable: `确定要禁用用户「${u.username}」吗？`,
    enable: `确定要启用用户「${u.username}」吗？`,
    unlock: `确定要解锁用户「${u.username}」吗？`
  }[actionTarget.value.action]
})

const actionButtonLabel = computed(() => {
  return { disable: '确认禁用', enable: '确认启用', unlock: '确认解锁' }[actionTarget.value?.action] || '确认'
})

async function executeAction() {
  const { user, action } = actionTarget.value
  actionLoading.value = true
  try {
    if (action === 'disable') {
      await updateUserStatus(user.id, false)
    } else if (action === 'enable') {
      await updateUserStatus(user.id, true)
    } else {
      await unlockUser(user.id)
    }
    ElMessage.success(action === 'disable' ? '账号已禁用' : action === 'enable' ? '账号已启用' : '账号已解锁')
    actionVisible.value = false
    // 若详情弹窗正展示该用户，同步刷新下钻数据
    if (detailVisible.value && detailUser.value?.id === user.id) {
      await loadDetailData(user.id)
    }
    await loadAll()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || e.response?.data?.error || e.response?.data?.detail || '操作失败')
  } finally {
    actionLoading.value = false
  }
}

// ===== 重置密码 =====
function openResetDialog(row) {
  resetTarget.value = row
  newPassword.value = ''
  resetResult.value = ''
  resetVisible.value = true
}

async function executeReset() {
  const pwd = newPassword.value.trim()
  if (pwd && pwd.length < 6) {
    ElMessage.warning('密码长度至少 6 位')
    return
  }
  resetLoading.value = true
  try {
    const res = await resetUserPassword(resetTarget.value.id, pwd || null)
    // 仅在此处返回新密码，供管理员一次性告知用户，不写入操作历史
    resetResult.value = res.data.new_password
    await loadAll()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || e.response?.data?.error || e.response?.data?.detail || '重置失败')
  } finally {
    resetLoading.value = false
  }
}

// ===== 用户申请列表 =====
async function loadMessages() {
  messagesLoading.value = true
  try {
    const params = { page: msgPage.value, page_size: msgPageSize.value }
    if (msgCategory.value) params.category = msgCategory.value
    if (msgStatus.value) params.status = msgStatus.value
    if (msgKeyword.value) params.keyword = msgKeyword.value
    const res = await listSupportMessages(params)
    messages.value = res.data.messages || []
    msgTotal.value = res.data.total || 0
  } catch (e) {
    console.error('获取用户申请失败:', e)
  } finally {
    messagesLoading.value = false
  }
}

// ===== 申请处理 =====
async function openMessageDetail(row) {
  messageDetail.value = { ...row }
  messageDetailVisible.value = true
  adminNote.value = ''
  attachmentUrl.value = ''
  userCandidates.value = []
  dsCandidates.value = []
  userSearch.value = ''
  dsSearch.value = ''
  applicantInfo.value = null
  applicantNotFound.value = false
  dsScope.value = null

  // 加载截图预览
  if (row.attachment_path) {
    try {
      const res = await downloadStorageFile(row.attachment_path)
      attachmentUrl.value = URL.createObjectURL(res.data)
    } catch {
      attachmentUrl.value = ''
    }
  }

  // 自动加载申请人账号信息（核实身份，防止恢复/解锁错对象；静默不弹提示）
  if (row.username) {
    userSearch.value = row.username
    await searchUser(true)
  }
  // 恢复数据集：仅待处理申请自动按申请人名下搜索已清空数据集（已处理的不再搜索，避免干扰）
  if (row.status !== 'done' && row.category === 'restore_dataset' && row.content?.dataset_name) {
    dsSearch.value = row.content.dataset_name
    const applicant = userCandidates.value.find(u => u.username === row.username)
    if (applicant) {
      dsScope.value = applicant.id
      await searchDatasets(applicant.id, true)
    } else {
      dsScope.value = null
      await searchDatasets(null, true)
    }
  }
}

function downloadAttachment() {
  if (!messageDetail.value?.attachment_path) return
  downloadStorageFile(messageDetail.value.attachment_path).then(res => {
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = messageDetail.value.attachment_name || 'screenshot'
    a.click()
    URL.revokeObjectURL(url)
  }).catch(() => ElMessage.error('下载失败'))
}

// 解锁专属操作：按用户名查询账号
// silent=true 表示自动触发（打开弹窗时），不弹提示，仅在候选区展示结果
async function searchUser(silent = false) {
  const keyword = userSearch.value.trim()
  if (!keyword) {
    if (!silent) ElMessage.warning('请输入用户名')
    return
  }
  const res = await listUsers({ search: keyword, page: 1, page_size: 20 })
  userCandidates.value = res.data.users || []
  if (!userCandidates.value.length && !silent) ElMessage.info('未找到匹配的账号')

  // 核实申请人身份：精确匹配申请填写的用户名
  const exact = userCandidates.value.find(u => u.username === messageDetail.value?.username)
  applicantInfo.value = exact || null
  applicantNotFound.value = !!messageDetail.value?.username && !exact && !userCandidates.value.length
}

async function doUnlockUser(user) {
  unlockLoading.value = true
  try {
    await unlockUser(user.id)
    ElMessage.success(`账号「${user.username}」已解锁`)
    // 刷新候选状态
    await searchUser()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || e.response?.data?.error || e.response?.data?.detail || '解锁失败')
  } finally {
    unlockLoading.value = false
  }
}

// 恢复数据集专属操作：搜索已清空(purged)数据集
// userId 为空时搜索全部用户；传入申请人 user_id 时限定其名下（防止恢复他人数据集）
// silent=true 表示自动触发（打开弹窗时），不弹提示，仅在候选区展示结果
async function searchDatasets(userId = null, silent = false) {
  const keyword = dsSearch.value.trim()
  if (!keyword) {
    if (!silent) ElMessage.warning('请输入搜索关键字')
    return
  }
  const params = { status: 'purged', keyword, page: 1, page_size: 20 }
  if (userId) params.user_id = userId
  const res = await listBusinessDatasets(params)
  dsCandidates.value = res.data.datasets || []
  if (!dsCandidates.value.length && !silent) {
    ElMessage.info(userId
      ? `申请人名下未找到匹配的已清空数据集（可能不属于该用户或文件已物理删除）`
      : '未找到匹配的已清空数据集，可在「数据管理-已清空」中确认')
  }
}

async function doRestoreDataset(ds) {
  restoreLoading.value = true
  try {
    await restorePurgedDataset(ds.id)
    ElMessage.success(`数据集「${ds.name}」已恢复到用户回收站`)
    // 刷新候选列表（保持当前搜索范围，静默避免恢复后空列表弹提示干扰）
    await searchDatasets(dsScope.value, true)
  } catch (e) {
    ElMessage.error(e.response?.data?.message || e.response?.data?.error || e.response?.data?.detail || '恢复失败')
  } finally {
    restoreLoading.value = false
  }
}

async function confirmProcess() {
  processLoading.value = true
  try {
    await processSupportMessage(messageDetail.value.id, adminNote.value)
    ElMessage.success('申请已标记为已处理')
    messageDetailVisible.value = false
    await loadMessages()
    // 若有待处理徽标统计可在此刷新
  } catch (e) {
    ElMessage.error(e.response?.data?.message || e.response?.data?.error || e.response?.data?.detail || '处理失败')
  } finally {
    processLoading.value = false
  }
}

// ===== 申请删除 =====
function openMessageDelete(row) {
  messageDeleteTarget.value = row
  messageDeleteVisible.value = true
}

async function confirmDeleteMessage() {
  messageDeleteLoading.value = true
  try {
    await deleteSupportMessage(messageDeleteTarget.value.id)
    ElMessage.success('申请已删除')
    messageDeleteVisible.value = false
    // 若正在详情弹窗中删除，一并关闭
    if (messageDetailVisible.value && messageDetail.value?.id === messageDeleteTarget.value.id) {
      messageDetailVisible.value = false
    }
    await loadMessages()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || e.response?.data?.error || e.response?.data?.detail || '删除失败')
  } finally {
    messageDeleteLoading.value = false
  }
}

onMounted(() => {
  loadAll()
  loadMessages()
  window.addEventListener('resize', onWindowResize)
})

function onWindowResize() {
  if (regTrendChart) regTrendChart.resize()
}

onUnmounted(() => {
  window.removeEventListener('resize', onWindowResize)
  if (regTrendChart) {
    regTrendChart.dispose()
    regTrendChart = null
  }
})
</script>

<style scoped>
.admin-tabs {
  margin-top: 4px;
}
.pending-badge {
  display: inline-block;
  margin-left: 8px;
  background: #f56c6c;
  color: #fff;
  font-size: 12px;
  line-height: 16px;
  padding: 0 6px;
  border-radius: 999px;
}
.message-detail {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.msg-content {
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 8px;
  padding: 12px 14px;
  background: #fafbfc;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.msg-row {
  display: flex;
  gap: 10px;
  font-size: 13px;
  color: var(--text-primary, #1e293b);
}
.msg-label {
  color: var(--text-secondary, #64748b);
  flex-shrink: 0;
  width: 70px;
}
.attachment-area {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}
.attachment-img {
  max-width: 320px;
  max-height: 220px;
  border-radius: 6px;
  border: 1px solid var(--border-color, #e2e8f0);
}
.attachment-loading {
  font-size: 12px;
  color: var(--text-secondary, #64748b);
}
.op-section {
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 8px;
  padding: 12px 14px;
}
.op-head {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #1e293b);
  margin-bottom: 10px;
}
.op-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.candidate-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.candidate-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--text-primary, #1e293b);
  background: #fff;
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 6px;
  padding: 8px 10px;
}
.candidate-main {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  flex-wrap: wrap;
}
.candidate-meta {
  font-size: 12px;
  color: var(--text-secondary, #64748b);
}
.applicant-info {
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: #fff;
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 6px;
  padding: 8px 10px;
}
.applicant-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--text-primary, #1e293b);
}
.candidate-empty {
  font-size: 12px;
  color: var(--text-secondary, #64748b);
}
.note-section {
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 8px;
  padding: 12px 14px;
}
</style>
