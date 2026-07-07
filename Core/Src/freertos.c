/* Core/Src/freertos.c */
#include "FreeRTOS.h"
#include "task.h"
#include "main.h"
#include "cmsis_os.h"
#include "app.h" 

// 引用外部标志位
extern volatile uint8_t sys_init_done;

/* Definitions for defaultTask */
osThreadId_t defaultTaskHandle;
const osThreadAttr_t defaultTask_attributes = {
  .name = "defaultTask",
  .stack_size = 2048 * 4, 
  .priority = (osPriority_t) osPriorityNormal,
};

/* Definitions for keyTask */
osThreadId_t keyTaskHandle;
const osThreadAttr_t keyTask_attributes = {
  .name = "keyTask",
  .stack_size = 1024 * 4,
  .priority = (osPriority_t) osPriorityAboveNormal, // 高优先级
};

void StartDefaultTask(void *argument);
void StartKeyTask(void *argument);

void MX_FREERTOS_Init(void) {
  defaultTaskHandle = osThreadNew(StartDefaultTask, NULL, &defaultTask_attributes);
  keyTaskHandle = osThreadNew(StartKeyTask, NULL, &keyTask_attributes);
}

// 任务 1：主业务 (负责初始化)
void StartDefaultTask(void *argument)
{
  // 这里包含了最耗时的操作：屏幕刷白、语音欢迎、称重去皮
  Checkout_Init();
  
  for(;;)
  {
    Checkout_Loop(); 
    osDelay(5); // 必须让出时间片
  }
}

// 任务 2：输入处理 (高优先级)
void StartKeyTask(void *argument)
{
  // 不再死等500ms，而是轮询标志位
  // 如果 Checkout_Init 里的 HX711_Init_Tare 耗时 2秒，这里就等 2秒。
  // 一旦标志位变1，立刻开始响应按键。
  while(sys_init_done == 0) {
      osDelay(50); 
  }

  for(;;)
  {
    App_Input_Task_Entry();
    osDelay(20); 
  }
}