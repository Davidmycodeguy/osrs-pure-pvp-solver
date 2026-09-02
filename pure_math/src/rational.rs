//! Exact rational numbers mirroring Python's `fractions.Fraction` as used by
//! `pure_solver.formula` and the combat kernel.  Values are arbitrary precision
//! (KO-window convolutions produce denominators far beyond 128 bits) and kept in
//! lowest terms with a positive denominator so equality/ordering match Python.

use std::cmp::Ordering;
use std::fmt;
use std::ops::{Add, Div, Mul, Neg, Sub};

use num_bigint::BigInt;
use num_integer::Integer;
use num_traits::{One, Signed, ToPrimitive, Zero};

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Rational {
    numerator: BigInt,
    denominator: BigInt,
}

impl Rational {
    pub fn zero() -> Rational {
        Rational::int(0)
    }

    pub fn one() -> Rational {
        Rational::int(1)
    }

    pub fn new(numerator: i128, denominator: i128) -> Rational {
        Rational::from_bigints(BigInt::from(numerator), BigInt::from(denominator))
    }

    pub fn from_bigints(numerator: BigInt, denominator: BigInt) -> Rational {
        assert!(!denominator.is_zero(), "Rational denominator must be non-zero");
        let divisor = numerator.gcd(&denominator);
        let (mut numerator, mut denominator) = if divisor.is_zero() {
            (numerator, denominator)
        } else {
            (numerator / &divisor, denominator / divisor)
        };
        if denominator.is_negative() {
            numerator = -numerator;
            denominator = -denominator;
        }
        Rational { numerator, denominator }
    }

    pub fn int(value: i128) -> Rational {
        Rational {
            numerator: BigInt::from(value),
            denominator: BigInt::one(),
        }
    }

    pub fn numerator(&self) -> &BigInt {
        &self.numerator
    }

    pub fn denominator(&self) -> &BigInt {
        &self.denominator
    }

    pub fn is_integer(&self) -> bool {
        self.denominator.is_one()
    }

    pub fn is_zero(&self) -> bool {
        self.numerator.is_zero()
    }

    pub fn is_negative(&self) -> bool {
        self.numerator.is_negative()
    }

    /// Python's `value // 1`: floor toward negative infinity.
    pub fn floor(&self) -> Rational {
        Rational {
            numerator: self.numerator.div_floor(&self.denominator),
            denominator: BigInt::one(),
        }
    }

    /// Python's `-(-v.numerator // v.denominator)`.
    pub fn ceil(&self) -> Rational {
        Rational {
            numerator: -((-&self.numerator).div_floor(&self.denominator)),
            denominator: BigInt::one(),
        }
    }

    /// Integer value after flooring, mirroring `int(fraction)` on a floored value.
    pub fn floor_i64(&self) -> i64 {
        self.numerator.div_floor(&self.denominator).to_i64().expect("floored rational exceeds i64")
    }

    /// Python's `int(fraction)`: truncation toward zero.
    pub fn trunc_i64(&self) -> i64 {
        if self.is_negative() {
            self.ceil().floor_i64()
        } else {
            self.floor_i64()
        }
    }

    /// Nearest `f64`, like Python's `float(Fraction)`.
    pub fn to_f64(&self) -> f64 {
        num_rational::Ratio::new_raw(self.numerator.clone(), self.denominator.clone())
            .to_f64()
            .expect("rational to f64")
    }

    pub fn max(self, other: Rational) -> Rational {
        if other > self {
            other
        } else {
            self
        }
    }

    /// Mean of a non-empty slice (`statistics.mean` on Fractions is exact).
    pub fn mean(values: &[Rational]) -> Rational {
        assert!(!values.is_empty(), "mean of empty slice");
        let total = values.iter().fold(Rational::zero(), |acc, v| &acc + v);
        &total / &Rational::int(values.len() as i128)
    }
}

impl From<i64> for Rational {
    fn from(value: i64) -> Rational {
        Rational::int(value as i128)
    }
}

macro_rules! binary_op {
    ($trait:ident, $method:ident, |$a:ident, $b:ident| $body:expr) => {
        impl<'a, 'b> $trait<&'b Rational> for &'a Rational {
            type Output = Rational;
            fn $method(self, other: &'b Rational) -> Rational {
                let ($a, $b) = (self, other);
                $body
            }
        }
        impl $trait<Rational> for Rational {
            type Output = Rational;
            fn $method(self, other: Rational) -> Rational {
                (&self).$method(&other)
            }
        }
        impl<'b> $trait<&'b Rational> for Rational {
            type Output = Rational;
            fn $method(self, other: &'b Rational) -> Rational {
                (&self).$method(other)
            }
        }
        impl<'a> $trait<Rational> for &'a Rational {
            type Output = Rational;
            fn $method(self, other: Rational) -> Rational {
                self.$method(&other)
            }
        }
    };
}

binary_op!(Add, add, |a, b| {
    if a.denominator == b.denominator {
        Rational::from_bigints(&a.numerator + &b.numerator, a.denominator.clone())
    } else {
        Rational::from_bigints(&a.numerator * &b.denominator + &b.numerator * &a.denominator, &a.denominator * &b.denominator)
    }
});
binary_op!(Sub, sub, |a, b| {
    if a.denominator == b.denominator {
        Rational::from_bigints(&a.numerator - &b.numerator, a.denominator.clone())
    } else {
        Rational::from_bigints(&a.numerator * &b.denominator - &b.numerator * &a.denominator, &a.denominator * &b.denominator)
    }
});
binary_op!(Mul, mul, |a, b| Rational::from_bigints(
    &a.numerator * &b.numerator,
    &a.denominator * &b.denominator
));
binary_op!(Div, div, |a, b| {
    assert!(!b.is_zero(), "division by zero rational");
    Rational::from_bigints(&a.numerator * &b.denominator, &a.denominator * &b.numerator)
});

impl Neg for Rational {
    type Output = Rational;
    fn neg(self) -> Rational {
        Rational {
            numerator: -self.numerator,
            denominator: self.denominator,
        }
    }
}

impl Neg for &Rational {
    type Output = Rational;
    fn neg(self) -> Rational {
        Rational {
            numerator: -&self.numerator,
            denominator: self.denominator.clone(),
        }
    }
}

impl PartialOrd for Rational {
    fn partial_cmp(&self, other: &Rational) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for Rational {
    fn cmp(&self, other: &Rational) -> Ordering {
        if self.denominator == other.denominator {
            return self.numerator.cmp(&other.numerator);
        }
        (&self.numerator * &other.denominator).cmp(&(&other.numerator * &self.denominator))
    }
}

impl fmt::Display for Rational {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.is_integer() {
            write!(formatter, "{}", self.numerator)
        } else {
            write!(formatter, "{}/{}", self.numerator, self.denominator)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::Rational;

    #[test]
    fn normalises_sign_and_lowest_terms() {
        assert_eq!(Rational::new(6, -4), Rational::new(-3, 2));
        assert_eq!(Rational::new(0, 7), Rational::zero());
    }

    #[test]
    fn floor_matches_python_floor_division() {
        assert_eq!(Rational::new(7, 2).floor(), Rational::int(3));
        assert_eq!(Rational::new(-7, 2).floor(), Rational::int(-4));
        assert_eq!(Rational::int(5).floor(), Rational::int(5));
        assert_eq!(Rational::new(7, 2).ceil(), Rational::int(4));
    }

    #[test]
    fn ordering_is_exact() {
        assert!(Rational::new(1, 3) < Rational::new(1, 2));
        assert_eq!(Rational::new(2, 4), Rational::new(1, 2));
        // The ranking test's exact-fraction tie order.
        let a = Rational::new(10i128.pow(18), 3 * 10i128.pow(18) + 1);
        let b = Rational::new(10i128.pow(18) + 1, 3 * 10i128.pow(18) + 3);
        assert!(b > a);
    }

    #[test]
    fn arithmetic_is_exact() {
        let half = Rational::new(1, 2);
        let third = Rational::new(1, 3);
        assert_eq!(&half + &third, Rational::new(5, 6));
        assert_eq!(&half - &third, Rational::new(1, 6));
        assert_eq!(&half * &third, Rational::new(1, 6));
        assert_eq!(&half / &third, Rational::new(3, 2));
        assert_eq!(Rational::mean(&[Rational::int(1), Rational::int(2)]), Rational::new(3, 2));
        assert_eq!(Rational::new(1, 3).to_f64(), 1.0 / 3.0);
    }
}
