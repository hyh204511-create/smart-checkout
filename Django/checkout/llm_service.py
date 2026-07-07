# -*- coding: utf-8 -*-
"""
Qwen 本地大模型桥接服务
通过 FastAPI 桥接 (start_llm_api.py) 调用 RK3588 NPU 上的 Qwen2.5-1.5B 模型
"""

import json
import logging
import threading
import uuid
import time
import re
import requests

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [Qwen-Bridge] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# 全局任务管理器 (内存字典)
task_manager = {}


class QwenBridgeService:
    """
    Qwen 大模型桥接服务
    - 通过 HTTP 调用 FastAPI 桥接层 (start_llm_api.py)
    - 桥接层内部通过 RKLLM C++ Runtime 驱动 NPU 上的 Qwen2.5-1.5B 模型
    - 所有分析任务异步执行，前端轮询获取结果
    """

    def __init__(self):
        self.api_url = "http://127.0.0.1:8080/v1/chat"
        self.request_timeout = 50  # NPU 推理超时 (秒)
        # 启动后台清理线程
        threading.Thread(target=self._auto_cleanup_loop, daemon=True).start()

    def _auto_cleanup_loop(self):
        """每 5 分钟清理超过 10 分钟的旧任务"""
        while True:
            time.sleep(300)
            self.cleanup_old_tasks(max_age=600)

    # ==================== 公共接口 ====================

    def trigger_analysis_task(self, json_data):
        """
        提交异步分析任务
        返回 task_id，前端通过 poll_ai_status 轮询结果
        """
        task_id = str(uuid.uuid4())
        task_manager[task_id] = {
            "status": "processing",
            "created_at": time.time()
        }
        logger.info(f"🎯 [Qwen] 触发分析任务 TaskID: {task_id}")
        threading.Thread(
            target=self._run_llm_analyze,
            args=(task_id, json_data),
            daemon=True
        ).start()
        return task_id

    def get_task_status(self, task_id):
        """查询任务状态"""
        task = task_manager.get(task_id)
        if task is None:
            return {"status": "not_found"}
        return {
            "status": task.get("status", "unknown"),
            "result": task.get("result"),
        }

    def cleanup_old_tasks(self, max_age=600):
        """清理过期任务"""
        now = time.time()
        stale = [tid for tid, t in task_manager.items()
                 if now - t.get("created_at", 0) > max_age]
        for tid in stale:
            del task_manager[tid]
        if stale:
            logger.debug(f"🧹 [Qwen] 清理了 {len(stale)} 个过期任务")

    # ==================== 内部实现 ====================

    def _run_llm_analyze(self, task_id, json_data):
        """在后台线程中执行 LLM 推理"""
        start_time = time.time()
        try:
            prompt = self._build_prompt(json_data)
            logger.debug(f"[{task_id}] 正在向 Qwen NPU 引擎发送请求...")

            response = requests.post(
                self.api_url,
                json={"prompt": prompt},
                timeout=self.request_timeout
            )

            req_time = time.time() - start_time
            logger.info(f"[{task_id}] Qwen API 响应: {response.status_code}, 耗时: {req_time:.2f}s")

            if response.status_code == 200:
                reply_text = response.json().get("reply", "")
                result = self._parse_llm_reply(reply_text, json_data)
                task_manager[task_id]["status"] = "completed"
                task_manager[task_id]["result"] = result
            else:
                result = self._fallback_report(json_data)
                task_manager[task_id]["status"] = "completed"
                task_manager[task_id]["result"] = result

        except Exception as e:
            logger.error(f"[{task_id}] Qwen API 请求异常: {e}")
            result = self._fallback_report(json_data)
            task_manager[task_id]["status"] = "completed"
            task_manager[task_id]["result"] = result

    def _build_prompt(self, json_data):
        """
        构建 Qwen 推理 Prompt
        - 纯文本模式：直接透传
        - 数据分析模式：异常驱动投喂 (库存 >20 积压 / ≤5 缺货)
        """
        # 纯文本模式
        if "prompt" in json_data:
            return json_data["prompt"].replace('\n', ' ')

        # 数据分析模式 (request_ai_analysis)
        stats = json_data.get("stats", {})
        products = json_data.get("products", [])
        orders = stats.get('order_count', 0)
        sales = stats.get('total_sales', 0)

        # 异常驱动投喂：标记库存异常商品
        product_details = []
        for p in products:
            raw_stock = float(p.get('stock', 0))
            stock_str = f"{int(raw_stock)}" if raw_stock.is_integer() else f"{raw_stock:.1f}"

            if raw_stock > 20:
                product_details.append(f"[{p['name']}](库存达{stock_str}件, 必须降价清理)")
            elif raw_stock <= 5:
                product_details.append(f"[{p['name']}](库存仅{stock_str}件, 必须紧急补货)")

        prod_str = "，".join(product_details) if product_details else "当前所有商品库存健康"

        prompt = (
            f"你是生鲜超市店长。今日数据：订单{orders}笔，营业额{sales:.2f}元。"
            f"异常商品警告：{prod_str}。"
            "【排版警告】绝对禁止使用句号，所有句子必须用逗号连接！"
            "严格按以下三个标题输出纯文本报告：\n"
            "整体评价：[一句话点评今日营收]\n"
            "紧急行动：[分行写出缺货商品的补货建议]\n"
            "商品调优：[分行写出积压商品的降价建议]"
        ).replace('\n', ' ')

        return prompt

    def _parse_llm_reply(self, reply_text, json_data):
        """
        解析 Qwen 返回的文本，提取结构化建议
        支持格式：整体评价 / 紧急行动 / 商品调优
        """
        result = {
            "overall_advice": "",
            "urgent_actions": [],
            "recommendations": []
        }

        # 1. 清洗输出
        reply_clean = reply_text.strip()
        # 移除 markdown 格式符号
        reply_clean = re.sub(r'[#*"`~]', '', reply_clean)
        # 移除开头的客套话
        reply_clean = re.sub(r'^(好的?[，,]\s*|没问题?[，,]\s*|收到[，,]\s*)', '', reply_clean).strip()
        # 全局替换中文句号为逗号
        reply_clean = reply_clean.replace('。', '，')
        # 保护小数点的前提下替换英文句号
        reply_clean = re.sub(r'(?<!\d)\.(?!\d)', '，', reply_clean)
        # 切除可能的复读机幻觉
        reply_clean = re.sub(r'瓜子和南瓜子.*?独立点评[，]?', '', reply_clean)
        reply_clean = re.sub(r'完全不同的独立商品[，]?', '', reply_clean)

        logger.debug(f"✂️ [Qwen] 清洗后输出:\n{reply_clean}")

        # 2. 正则解析三段式输出
        overall_match = re.search(r'整体评价[：:]\s*(.*?)(?=紧急行动[：:]|商品调优[：:]|$)', reply_clean, re.DOTALL)
        urgent_match = re.search(r'紧急行动[：:]\s*(.*?)(?=商品调优[：:]|$)', reply_clean, re.DOTALL)
        recom_match = re.search(r'商品调优[：:]\s*(.*)', reply_clean, re.DOTALL)

        overall_text = overall_match.group(1).strip() if overall_match else ""
        urgent_text = urgent_match.group(1).strip() if urgent_match else ""
        recom_text = recom_match.group(1).strip() if recom_match else ""

        def clean_sentence(s):
            """切除句子开头的无用序号"""
            return re.sub(r'^[\d.\-、\s]+', '', s).strip()

        # 3. 整体评价
        if len(overall_text) > 5:
            result["overall_advice"] = overall_text.replace('\n', ' ').rstrip('，')
        else:
            stats = json_data.get("stats", {})
            result["overall_advice"] = (
                f"今日共处理 {stats.get('order_count', 0)} 个订单，"
                f"总营业额 {stats.get('total_sales', 0):.2f} 元"
            )

        # 4. 紧急行动
        if urgent_text:
            sentences = urgent_text.split('\n')
            for s in sentences:
                s_clean = clean_sentence(s).rstrip('，')
                if len(s_clean) > 3 and "商品调优" not in s_clean:
                    result["urgent_actions"].append(s_clean)

        # 5. 商品调优建议 — 按商品名匹配
        products = json_data.get("products", [])
        recom_sentences = recom_text.split('\n')
        recom_sentences = [clean_sentence(s).rstrip('，') for s in recom_sentences
                          if len(clean_sentence(s)) > 3]

        for p in products:
            p_name = p["name"]
            raw_stock = float(p.get("stock", 0.0))
            stock_str = f"{int(raw_stock)}" if raw_stock.is_integer() else f"{raw_stock:.1f}"

            # 严格隔离商品文本 (防止 "瓜子" 匹配到 "南瓜子")
            relevant_sentences = []
            for s in recom_sentences:
                if p_name == "瓜子":
                    if "瓜子" in s and "南瓜子" not in s and "冬瓜子" not in s:
                        relevant_sentences.append(s)
                else:
                    if p_name in s:
                        relevant_sentences.append(s)

            if relevant_sentences:
                reason = "，".join(relevant_sentences).strip()
                # 语义打标签
                if any(w in reason for w in ["降价", "下调", "打折", "促销", "清理", "积压"]):
                    action = "降价"
                elif any(w in reason for w in ["提价", "上调", "涨价"]):
                    action = "提价"
                elif any(w in reason for w in ["补货", "进货", "缺货"]):
                    action = "补货"
                else:
                    action = "建议"

                result["recommendations"].append({
                    "name": p_name,
                    "action_type": action,
                    "reason": reason
                })
            else:
                # Qwen 未覆盖此商品，使用规则兜底
                if raw_stock <= 5:
                    action, reason = "补货", f"库存不足 (仅剩 {stock_str} 件)，建议立即补货"
                elif raw_stock > 20:
                    action, reason = "降价", f"库存积压 (达 {stock_str} 件)，建议降价清理促销"
                else:
                    action, reason = "保持", "库存与售价维持在健康水平，无需调整"

                result["recommendations"].append({
                    "name": p_name,
                    "action_type": action,
                    "reason": reason
                })

        # 6. 紧急行动二级安全补全
        if not result["urgent_actions"]:
            alerts = json_data.get("alerts", [])
            if alerts:
                for item in alerts[:5]:
                    name = item.get("name", "商品")
                    raw_stock = float(item.get("stock", 0))
                    stock_str = f"{int(raw_stock)}" if raw_stock.is_integer() else f"{raw_stock:.1f}"
                    result["urgent_actions"].append(
                        f"{name}：库存仅剩 {stock_str} 件，建议立即采购补货"
                    )
            else:
                result["urgent_actions"].append("当前暂无极度缺货商品，库存状况良好")

        return result

    def _fallback_report(self, json_data):
        """API 不可用时的纯规则兜底报告"""
        return self._parse_llm_reply("", json_data)


# 全局单例 — 供 views.py 直接使用
local_ai = QwenBridgeService()
