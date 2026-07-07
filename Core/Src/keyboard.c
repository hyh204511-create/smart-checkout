/* Core/Src/keyboard.c */
#include "keyboard.h"

// 键值映射表 (4x4)
static const char KEY_MAP[4][4] = {
    {'1', '2', '3', 'A'},
    {'4', '5', '6', 'B'},
    {'7', '8', '9', 'C'},
    {'*', '0', '#', 'D'}
};

// 辅助：读取指定列的电平
static GPIO_PinState Read_Col(uint8_t col_index) {
    switch(col_index) {
        case 0: return HAL_GPIO_ReadPin(KEY_C1_PORT, KEY_C1_PIN);
        case 1: return HAL_GPIO_ReadPin(KEY_C2_PORT, KEY_C2_PIN);
        case 2: return HAL_GPIO_ReadPin(KEY_C3_PORT, KEY_C3_PIN);
        case 3: return HAL_GPIO_ReadPin(KEY_C4_PORT, KEY_C4_PIN);
        default: return GPIO_PIN_SET;
    }
}

// 辅助：拉高所有行 (复位状态)
static void Set_All_Rows_High(void) {
    HAL_GPIO_WritePin(KEY_R1_PORT, KEY_R1_PIN, GPIO_PIN_SET);
    HAL_GPIO_WritePin(KEY_R2_PORT, KEY_R2_PIN, GPIO_PIN_SET);
    HAL_GPIO_WritePin(KEY_R3_PORT, KEY_R3_PIN, GPIO_PIN_SET);
    HAL_GPIO_WritePin(KEY_R4_PORT, KEY_R4_PIN, GPIO_PIN_SET);
}

// 辅助：拉低指定行
static void Set_Row_Low(uint8_t row_index) {
    Set_All_Rows_High(); // 先全部拉高
    switch(row_index) {
        case 0: HAL_GPIO_WritePin(KEY_R1_PORT, KEY_R1_PIN, GPIO_PIN_RESET); break;
        case 1: HAL_GPIO_WritePin(KEY_R2_PORT, KEY_R2_PIN, GPIO_PIN_RESET); break;
        case 2: HAL_GPIO_WritePin(KEY_R3_PORT, KEY_R3_PIN, GPIO_PIN_RESET); break; // PE12
        case 3: HAL_GPIO_WritePin(KEY_R4_PORT, KEY_R4_PIN, GPIO_PIN_RESET); break;
    }
}

void Keypad_Init(void) {
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    // 1. 开启时钟 (B, C, G, E)
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();
    __HAL_RCC_GPIOG_CLK_ENABLE();
    __HAL_RCC_GPIOE_CLK_ENABLE();

    // 2. 配置行线 (推挽输出)
    GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;

    // R1, R2, R4 在 GPIOB
    GPIO_InitStruct.Pin = KEY_R1_PIN | KEY_R2_PIN | KEY_R4_PIN;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

    // R3 在 GPIOE
    GPIO_InitStruct.Pin = KEY_R3_PIN;
    HAL_GPIO_Init(GPIOE, &GPIO_InitStruct);

    // 3. 配置列线 (上拉输入)
    GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
    GPIO_InitStruct.Pull = GPIO_PULLUP;
    
    GPIO_InitStruct.Pin = KEY_C1_PIN; HAL_GPIO_Init(KEY_C1_PORT, &GPIO_InitStruct);
    GPIO_InitStruct.Pin = KEY_C2_PIN; HAL_GPIO_Init(KEY_C2_PORT, &GPIO_InitStruct);
    GPIO_InitStruct.Pin = KEY_C3_PIN; HAL_GPIO_Init(KEY_C3_PORT, &GPIO_InitStruct);
    GPIO_InitStruct.Pin = KEY_C4_PIN; HAL_GPIO_Init(KEY_C4_PORT, &GPIO_InitStruct);

    // 4. 默认拉高所有行
    Set_All_Rows_High();
}

static void Keypad_Delay(void) {
    for(volatile int i=0; i<2000; i++); 
}

char Keypad_Scan(void) {
    for (int row = 0; row < 4; row++) {
        // 1. 拉低当前行
        Set_Row_Low(row);
        Keypad_Delay();

        // 2. 遍历列
        for (int col = 0; col < 4; col++) {
            if (Read_Col(col) == GPIO_PIN_RESET) {
                Keypad_Delay(); // 去抖
                if (Read_Col(col) == GPIO_PIN_RESET) {
                    // 等待松手
                    while(Read_Col(col) == GPIO_PIN_RESET);
                    Set_All_Rows_High(); // 恢复
                    return KEY_MAP[row][col];
                }
            }
        }
    }
    Set_All_Rows_High();
    return KEY_NONE;
}