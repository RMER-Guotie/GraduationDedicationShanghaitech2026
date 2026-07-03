/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : Header for main.c file.
  *                   This file contains the common defines of the application.
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "stm32f1xx_hal.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Exported types ------------------------------------------------------------*/
/* USER CODE BEGIN ET */

/* USER CODE END ET */

/* Exported constants --------------------------------------------------------*/
/* USER CODE BEGIN EC */

/* USER CODE END EC */

/* Exported macro ------------------------------------------------------------*/
/* USER CODE BEGIN EM */

/* USER CODE END EM */

/* Exported functions prototypes ---------------------------------------------*/
void Error_Handler(void);

/* USER CODE BEGIN EFP */

/* USER CODE END EFP */

/* Private defines -----------------------------------------------------------*/
#define SYNC_Pin GPIO_PIN_15
#define SYNC_GPIO_Port GPIOC
#define CH1_Pin GPIO_PIN_0
#define CH1_GPIO_Port GPIOA
#define CH2_Pin GPIO_PIN_1
#define CH2_GPIO_Port GPIOA
#define CH3_Pin GPIO_PIN_2
#define CH3_GPIO_Port GPIOA
#define CH4_Pin GPIO_PIN_3
#define CH4_GPIO_Port GPIOA
#define RC_D3_Pin GPIO_PIN_1
#define RC_D3_GPIO_Port GPIOB
#define RC_D3_EXTI_IRQn EXTI1_IRQn
#define RC_D2_Pin GPIO_PIN_2
#define RC_D2_GPIO_Port GPIOB
#define RC_D2_EXTI_IRQn EXTI2_IRQn
#define RC_D1_Pin GPIO_PIN_10
#define RC_D1_GPIO_Port GPIOB
#define RC_D1_EXTI_IRQn EXTI15_10_IRQn
#define RC_D0_Pin GPIO_PIN_11
#define RC_D0_GPIO_Port GPIOB
#define RC_D0_EXTI_IRQn EXTI15_10_IRQn
#define SPI2_CS0_Pin GPIO_PIN_12
#define SPI2_CS0_GPIO_Port GPIOB

/* USER CODE BEGIN Private defines */

/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
