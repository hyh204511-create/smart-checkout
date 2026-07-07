/* Inc/keyboard.h */
#ifndef __KEYBOARD_H
#define __KEYBOARD_H

#include "main.h"

// --- 硬件引脚定义 ---

// 行线 (Rows) - 推挽输出
// 支持不同端口
#define KEY_R1_PORT     GPIOB
#define KEY_R1_PIN      GPIO_PIN_6

#define KEY_R2_PORT     GPIOB
#define KEY_R2_PIN      GPIO_PIN_7

#define KEY_R3_PORT     GPIOE       // R3 为 PE12 (原 PB12 被下载器占用)
#define KEY_R3_PIN      GPIO_PIN_12

#define KEY_R4_PORT     GPIOB
#define KEY_R4_PIN      GPIO_PIN_9

// 列线 (Cols) - 上拉输入 (保持不变)
#define KEY_C1_PORT     GPIOC
#define KEY_C1_PIN      GPIO_PIN_6

#define KEY_C2_PORT     GPIOC
#define KEY_C2_PIN      GPIO_PIN_7

#define KEY_C3_PORT     GPIOG
#define KEY_C3_PIN      GPIO_PIN_6

#define KEY_C4_PORT     GPIOG
#define KEY_C4_PIN      GPIO_PIN_7

// --- 按键值定义 (保持不变) ---
#define KEY_NONE        0
#define KEY_CONFIRM     'A' 
#define KEY_DELETE      'B' 
#define KEY_CLEAR       'C' 
#define KEY_MODE        'D' 
#define KEY_UPLOAD      '#' 
#define KEY_DEBUG       '*' 

// 函数声明
void Keypad_Init(void);
char Keypad_Scan(void);

#endif