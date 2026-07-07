/* Core/Inc/app.h */
#ifndef __APP_H
#define __APP_H

#include "main.h"

// 变量类型定义
typedef enum { MODE_MANUAL = 0, MODE_AUTO = 1 } SystemMode_t;
extern volatile SystemMode_t current_mode; 

void Checkout_Init(void);
void Checkout_Loop(void);

// 供 FreeRTOS 任务调用的输入处理入口
void App_Input_Task_Entry(void);

#endif